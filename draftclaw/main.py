"""
Entry point for the DraftClaw paper review pipeline.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys as _sys

_sys.path.insert(0, str(Path(__file__).parent))

from agents.explore_agent import ExploreAgent
from agents.language_switch_agent import ReportLanguageSwitchAgent, normalize_report_language
from agents.llm_utils import LLMRequestCancelled, llm_cancel_context
from agents.plan_agent import PlanAgent
from agents.recheck_agent import RecheckAgent
from agents.search_agent import SearchAgent
from agents.summary_agent import SummaryAgent
from agents.vision_agent import VisionValidationAgent
from bbox_locator import BBoxLocator
from chunker import Chunk, ChunkSplitter
from config import (
    ADJACENT_IMAGE_GROUP_SIZE,
    BBOX_NORMALIZED_SIZE,
    BBOX_MATCH_LIMIT,
    CACHE_DIR,
    LOCAL_CHUNK_MAX_SIZE,
    LOCAL_CHUNK_MIN_SIZE,
    MAX_IMAGES_PER_CHUNK,
    REPORT_HTML_ENABLED,
    REPORT_LANGUAGE,
    RECHECK_LLM_ENABLED,
    RECHECK_VLM_ENABLED,
    REVIEW_EXCERPT_MAX_CHARS,
    REVIEW_PARALLELISM,
    SAVE_BBOX_DEBUG_SCREENSHOTS,
    SEND_IMAGES_TO_LLM,
    VISION_BBOX_PADDING,
    VISION_CROP_ZOOM,
    VISION_MAX_MATCH_IMAGES,
    VISION_PAGE_ZOOM,
    normalize_review_mode,
    resolve_review_mode_features,
)
from logger import AgentLogger
from issue_review import ensure_issue_review_defaults, get_issue_review_decision
from pdf_screenshot import PDFIssueScreenshotRenderer
from pdf_parser import PDFParser, load_cached_parse_result, save_parse_result
from report_renderer import render_review_report_html


IMAGE_MARKDOWN_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
IMAGE_LINE_PATTERN = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")


class ReviewCancelled(RuntimeError):
    """Raised when a user cancels an in-flight review."""


def raise_if_review_cancelled(cancel_check: Any = None) -> None:
    if callable(cancel_check) and cancel_check():
        raise ReviewCancelled("Review cancelled by user")


def get_cache_dir(pdf_path: str) -> Path:
    pdf_name = Path(pdf_path).stem
    return CACHE_DIR / f"{pdf_name}_files"


def normalize_chunk_id_list(value: Any) -> List[int]:
    chunk_ids: List[int] = []
    seen = set()
    if not isinstance(value, list):
        return chunk_ids
    for item in value:
        try:
            chunk_id = int(item)
        except (TypeError, ValueError):
            continue
        if chunk_id < 0 or chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk_ids.append(chunk_id)
    return sorted(chunk_ids)


def resolve_agent_artifact_dir(
    *,
    logger: Any,
    subdir_key: str,
    cache_dir: Path,
    fallback_name: str,
) -> Path:
    logger_subdirs = getattr(logger, "subdirs", {}) or {}
    if subdir_key in logger_subdirs:
        return Path(logger_subdirs[subdir_key])

    base_cache_dir = Path(cache_dir or "")
    if not str(base_cache_dir).strip() or str(base_cache_dir) == ".":
        base_cache_dir = CACHE_DIR / "_scratch"
    elif not base_cache_dir.is_absolute():
        base_cache_dir = CACHE_DIR / base_cache_dir
    return base_cache_dir / fallback_name


def build_document_overview(markdown_content: str, max_sections: int = 12) -> str:
    full_markdown = strip_markdown_image_lines(markdown_content).strip()
    return full_markdown


def build_explore_document_overview(document_overview: str, current_chunk: str) -> str:
    overview = strip_markdown_image_lines(document_overview).strip()
    chunk_text = str(current_chunk or "").strip()
    if overview:
        marked = mark_current_chunk_in_document_overview(overview, chunk_text)
        return marked or overview
    return chunk_text


def mark_current_chunk_in_document_overview(document_overview: str, current_chunk: str) -> str:
    overview = strip_markdown_image_lines(document_overview)
    chunk_text = strip_markdown_image_lines(current_chunk).strip()
    if not overview.strip() or not chunk_text:
        return overview
    if "<current chunk>" in overview and "</current chunk>" in overview:
        return overview

    marker = "Full PDF Markdown:\n"
    prefix, separator, body = overview.partition(marker)
    target = body if separator else overview
    target_prefix = f"{prefix}{separator}" if separator else ""

    marked_target = _wrap_current_chunk_match(target, chunk_text)
    if marked_target is None:
        return overview
    return f"{target_prefix}{marked_target}"


def _wrap_current_chunk_match(text: str, chunk_text: str) -> Optional[str]:
    index = text.find(chunk_text)
    match_length = len(chunk_text)

    if index < 0:
        probe = chunk_text[: min(len(chunk_text), 1200)].strip()
        if len(probe) < 80:
            return None
        index = text.find(probe)
        match_length = len(probe)
        if index < 0:
            return None

    return (
        f"{text[:index]}<current chunk>\n"
        f"{text[index:index + match_length]}\n"
        f"</current chunk>{text[index + match_length:]}"
    )


def build_global_chunk_map(plan_records: List[Dict[str, Any]], max_chars: int = 7000) -> str:
    entries: List[str] = []
    current_length = 0

    for record in sorted(plan_records, key=lambda item: int(item.get("chunk_id", 0) or 0)):
        plan_output = record.get("plan_output", {})
        chunk_id = int(record.get("chunk_id", 0) or 0)
        entry = (
            f"[Chunk {chunk_id}]\n"
            f"section_role: {str(plan_output.get('section_role', '')).strip()}\n"
            f"chunk_purpose: {str(plan_output.get('chunk_purpose', '')).strip()}\n"
            f"core_content: {str(plan_output.get('core_content', '')).strip()}\n"
            f"visual_element_role: {str(plan_output.get('visual_element_role', '')).strip()}"
        ).strip()
        entry_length = len(entry) + 2
        if entries and current_length + entry_length > max_chars:
            break
        entries.append(entry)
        current_length += entry_length

    return "\n\n".join(entries).strip()


def build_neighbor_context(chunks: List[Chunk], chunk_index: int, edge_chars: int = 800) -> str:
    context_parts: List[str] = []

    if chunk_index > 0:
        previous_chunk = chunks[chunk_index - 1]
        previous_text = strip_markdown_image_lines(previous_chunk.content)
        context_parts.append(
            f"[Previous chunk tail]\n{previous_text[-edge_chars:]}"
        )

    if chunk_index + 1 < len(chunks):
        next_chunk = chunks[chunk_index + 1]
        next_text = strip_markdown_image_lines(next_chunk.content)
        context_parts.append(
            f"[Next chunk head]\n{next_text[:edge_chars]}"
        )

    return "\n\n".join(context_parts)


def build_anchored_text(
    locator: Any,
    text: str,
    *,
    max_anchors: int = 120,
) -> str:
    if not locator or not str(text or "").strip():
        return str(text or "")
    return locator.build_anchored_text(text, max_anchors=max_anchors)


def summarize_vision_validation(summary: Dict[str, Any]) -> str:
    return (
        f"kept={summary.get('kept_issues', 0)} | "
        f"dropped={summary.get('dropped_issues', 0)} | "
        f"review={summary.get('review_issues', 0)} | "
        f"skipped={summary.get('skipped_issues', 0)}"
    )


def summarize_bbox_debug(summary: Dict[str, Any]) -> str:
    return (
        f"saved={summary.get('saved_screenshots', 0)} | "
        f"issues={summary.get('issues_with_screenshots', 0)} | "
        f"coord=normalized_{summary.get('bbox_normalized_size', 1000)}"
    )


def ensure_issue_vision_validation(
    issue: Dict[str, Any],
    *,
    vision_enabled: bool,
) -> Dict[str, Any]:
    existing = issue.get("vision_validation")
    if isinstance(existing, dict) and str(existing.get("decision", "")).strip():
        return issue

    reason = "Vision validation was not executed for this issue."
    if not vision_enabled:
        reason = "Vision validation is disabled for this run."

    issue["vision_validation"] = {
        "validated": False,
        "decision": "skip",
        "confidence": "low",
        "reason": reason,
        "model": "",
        "screenshot_count": 0,
    }
    return issue


def save_bbox_debug_screenshots(
    *,
    issues: List[Dict[str, Any]],
    pdf_path: str,
    logger: AgentLogger,
    enabled: bool,
) -> Dict[str, Any]:
    summary = {
        "enabled": enabled,
        "bbox_normalized_size": int(BBOX_NORMALIZED_SIZE),
        "issues_with_screenshots": 0,
        "saved_screenshots": 0,
        "output_dir": "",
    }
    if not enabled:
        return {"issues": issues, "summary": summary}

    output_dir = logger.subdirs["bbox_debug"] / "screenshots"
    renderer = PDFIssueScreenshotRenderer(
        pdf_path,
        output_dir,
        page_zoom=VISION_PAGE_ZOOM,
        crop_zoom=VISION_CROP_ZOOM,
        bbox_padding=VISION_BBOX_PADDING,
        max_matches=None,
        bbox_normalized_size=BBOX_NORMALIZED_SIZE,
    )
    try:
        for issue_index, issue in enumerate(issues, start=1):
            screenshots = renderer.render_issue(issue, issue_index, max_matches=None)
            issue["bbox_debug_screenshots"] = [
                {
                    "kind": item.get("kind"),
                    "page": item.get("page"),
                    "bbox": item.get("bbox"),
                    "page_bbox": item.get("page_bbox"),
                    "bbox_coordinate_system": item.get("bbox_coordinate_system"),
                    "matched_text": item.get("matched_text"),
                    "local_path": item.get("local_path"),
                }
                for item in screenshots
            ]
            if screenshots:
                summary["issues_with_screenshots"] += 1
                summary["saved_screenshots"] += len(screenshots)
                logger.log(
                    "BBoxDebug",
                    "output",
                    chunk_id=issue.get("chunk_id"),
                    input_data={
                        "type": issue.get("type"),
                        "evidence": issue.get("evidence"),
                        "location": issue.get("location"),
                    },
                    output_data={
                        "bbox_normalized_size": BBOX_NORMALIZED_SIZE,
                        "screenshots": issue["bbox_debug_screenshots"],
                    },
                    message=f"Saved {len(screenshots)} bbox debug screenshots",
                )
        summary["output_dir"] = str(output_dir)
        return {"issues": issues, "summary": summary}
    finally:
        renderer.close()


def apply_vision_validation(
    *,
    issues: List[Dict[str, Any]],
    pdf_path: str,
    logger: AgentLogger,
    enabled: bool,
) -> Dict[str, Any]:
    vision_agent = VisionValidationAgent(logger=logger)
    screenshots_dir = logger.subdirs["vision_agent"] / "screenshots"
    renderer = PDFIssueScreenshotRenderer(
        pdf_path,
        screenshots_dir,
        page_zoom=VISION_PAGE_ZOOM,
        crop_zoom=VISION_CROP_ZOOM,
        bbox_padding=VISION_BBOX_PADDING,
        max_matches=VISION_MAX_MATCH_IMAGES,
        bbox_normalized_size=BBOX_NORMALIZED_SIZE,
    )

    kept_issues: List[Dict[str, Any]] = []
    rejected_issues: List[Dict[str, Any]] = []
    metrics_list: List[Dict[str, Any]] = []
    summary = {
        "enabled": bool(enabled and vision_agent.enabled),
        "total_input_issues": len(issues),
        "validated_issues": 0,
        "kept_issues": 0,
        "dropped_issues": 0,
        "review_issues": 0,
        "skipped_issues": 0,
    }
    if not enabled:
        summary["reason"] = "Vision agent disabled."
        return {
            "issues": issues,
            "rejected_issues": rejected_issues,
            "summary": summary,
            "llm_metrics_list": metrics_list,
        }

    try:
        for issue_index, issue in enumerate(issues, start=1):
            try:
                screenshots = [
                    {
                        "kind": item.get("kind"),
                        "page": item.get("page"),
                        "bbox": item.get("bbox"),
                        "page_bbox": item.get("page_bbox"),
                        "bbox_coordinate_system": item.get("bbox_coordinate_system"),
                        "matched_text": item.get("matched_text"),
                        "local_path": item.get("local_path"),
                        "page_idx": int(item.get("page", 1) or 1) - 1,
                        "image_caption": [
                            (
                                f"{item.get('kind')} bbox screenshot | "
                                f"normalized_bbox {item.get('bbox')} | "
                                f"page_bbox {item.get('page_bbox')} | "
                                f"coord {item.get('bbox_coordinate_system', f'normalized_{BBOX_NORMALIZED_SIZE}')}"
                            )
                        ],
                    }
                    for item in issue.get("bbox_debug_screenshots", [])[:VISION_MAX_MATCH_IMAGES]
                    if item.get("local_path")
                ]
                if not screenshots:
                    screenshots = renderer.render_issue(issue, issue_index)
                validation = vision_agent.validate_issue(
                    issue=issue,
                    issue_index=issue_index,
                    chunk_id=issue.get("chunk_id"),
                    screenshots=screenshots,
                )
                llm_metrics = validation.pop("_llm_metrics", {})
                if llm_metrics:
                    metrics_list.append(llm_metrics)
            except Exception as exc:
                logger.log(
                    "VisionAgent",
                    "error",
                    chunk_id=issue.get("chunk_id"),
                    input_data={
                        "issue_index": issue_index,
                        "issue": {
                            "type": issue.get("type"),
                            "description": issue.get("description"),
                            "evidence": issue.get("evidence"),
                            "location": issue.get("location"),
                        },
                    },
                    message=f"Vision validation failed: {exc}",
                )
                screenshots = []
                validation = {
                    "validated": False,
                    "decision": "skip",
                    "confidence": "low",
                    "reason": f"Vision validation failed: {exc}",
                    "model": getattr(vision_agent, 'client', None).model if getattr(vision_agent, 'client', None) else "",
                    "screenshot_count": 0,
                }

            issue["vision_validation"] = validation
            issue["vision_screenshots"] = [
                {
                    "kind": item.get("kind"),
                    "page": item.get("page"),
                    "bbox": item.get("bbox"),
                    "matched_text": item.get("matched_text"),
                    "local_path": item.get("local_path"),
                }
                for item in screenshots
            ]

            decision = str(validation.get("decision", "review") or "review").strip().lower()
            if decision != "skip":
                summary["validated_issues"] += 1
            if decision == "drop":
                rejected_issues.append(deepcopy(issue))
                summary["dropped_issues"] += 1
                continue
            if decision == "review":
                summary["review_issues"] += 1
            elif decision == "skip":
                summary["skipped_issues"] += 1
            kept_issues.append(issue)

        summary["kept_issues"] = len(kept_issues)
        return {
            "issues": kept_issues,
            "rejected_issues": rejected_issues,
            "summary": summary,
            "llm_metrics_list": metrics_list,
        }
    finally:
        renderer.close()


def count_markdown_image_lines(text: str) -> int:
    return len(IMAGE_MARKDOWN_PATTERN.findall(str(text or "")))


def strip_markdown_image_lines(text: str) -> str:
    cleaned_lines: List[str] = []
    for line in str(text or "").splitlines():
        cleaned = IMAGE_MARKDOWN_PATTERN.sub("", line).strip()
        if cleaned:
            cleaned_lines.append(re.sub(r"[ \t]{2,}", " ", cleaned))
    return "\n".join(cleaned_lines)


def normalize_relative_image_path(path_value: str) -> str:
    normalized = str(path_value).replace("\\", "/").strip()
    if "images/" in normalized:
        normalized = normalized[normalized.index("images/") :]
    return normalized.lstrip("/")


def count_available_local_images(images: List[Dict[str, Any]]) -> int:
    count = 0
    for image in images:
        local_path = image.get("local_path")
        if local_path and Path(local_path).exists():
            count += 1
    return count


def count_bbox_pages(bbox_json: Any) -> int:
    if isinstance(bbox_json, dict):
        if bbox_json.get("source") == "content_list_v2":
            return int(bbox_json.get("page_count", 0) or 0)
        pdf_info = bbox_json.get("pdf_info")
        if isinstance(pdf_info, list):
            return len(pdf_info)
    if isinstance(bbox_json, list):
        return len(bbox_json)
    return 0


def needs_multimodal_asset_refresh(parse_result: Any) -> bool:
    if not SEND_IMAGES_TO_LLM:
        return False
    if not parse_result or not getattr(parse_result, "images", None):
        return False
    return count_available_local_images(parse_result.images) < len(parse_result.images)


def needs_parser_backend_refresh(parse_result: Any) -> bool:
    if not parse_result:
        return False
    cached_backend = str(getattr(parse_result, "parser_backend", "") or "").strip().lower()
    return cached_backend != "mineru"


def needs_cached_artifact_refresh(pdf_path: str, parse_result: Any) -> bool:
    if not parse_result:
        return False
    cache_dir = get_cache_dir(pdf_path)
    pdf_name = Path(pdf_path).stem
    bbox_debug_path = cache_dir / f"{pdf_name}_bbox_debug.md"
    legacy_figures_path = cache_dir / f"{pdf_name}_figures.json"
    legacy_figures_dir = cache_dir / "figures"
    bbox_json = getattr(parse_result, "bbox_json", {})
    return (
        not bbox_debug_path.exists()
        or not isinstance(bbox_json, dict)
        or bbox_json.get("source") != "content_list_v2"
        or legacy_figures_path.exists()
        or legacy_figures_dir.exists()
    )


def split_chunk_image_runs(chunk_content: str) -> List[List[str]]:
    runs: List[List[str]] = []
    current_run: List[str] = []

    for raw_line in chunk_content.splitlines():
        stripped = raw_line.strip()
        image_match = IMAGE_LINE_PATTERN.match(stripped)
        if image_match:
            normalized = normalize_relative_image_path(image_match.group(1))
            if normalized:
                current_run.append(normalized)
            continue

        if not stripped:
            continue

        if current_run:
            runs.append(current_run)
            current_run = []

    if current_run:
        runs.append(current_run)

    return runs


def chunk_image_run_groups(image_runs: List[List[str]], group_size: int) -> List[List[str]]:
    grouped_paths: List[List[str]] = []
    effective_size = max(1, group_size)
    for run in image_runs:
        for start_index in range(0, len(run), effective_size):
            grouped_paths.append(run[start_index : start_index + effective_size])
    return grouped_paths


def compose_llm_image_group(cache_dir: Path, group_paths: List[str], image_map: Dict[str, Dict[str, Any]]) -> str:
    local_paths: List[Path] = []
    for relative_path in group_paths:
        image = image_map.get(relative_path)
        local_path = Path(str(image.get("local_path", ""))) if image else Path()
        if local_path.exists():
            local_paths.append(local_path)

    if not local_paths:
        return ""

    output_dir = cache_dir / "llm_image_groups"
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1("||".join(path.as_posix() for path in local_paths).encode("utf-8")).hexdigest()[:16]
    output_path = output_dir / f"group_{digest}.jpg"
    if output_path.exists():
        return str(output_path.resolve())

    if len(local_paths) == 1:
        shutil.copyfile(local_paths[0], output_path)
        return str(output_path.resolve())

    try:
        from PIL import Image
    except ImportError:
        shutil.copyfile(local_paths[0], output_path)
        return str(output_path.resolve())

    rendered_images = []
    for local_path in local_paths:
        with Image.open(local_path) as source_image:
            rendered_images.append(source_image.convert("RGB"))

    max_height = max(image.height for image in rendered_images)
    total_width = sum(image.width for image in rendered_images)
    canvas = Image.new("RGB", (max(total_width, 1), max(max_height, 1)), "white")

    current_x = 0
    for image in rendered_images:
        offset_y = max((max_height - image.height) // 2, 0)
        canvas.paste(image, (current_x, offset_y))
        current_x += image.width

    canvas.save(output_path, quality=95)
    return str(output_path.resolve())


def collect_chunk_image_inputs(
    chunk_content: str,
    document_images: List[Dict[str, Any]],
    *,
    cache_dir: Path,
    group_size: int = ADJACENT_IMAGE_GROUP_SIZE,
    max_images: int = MAX_IMAGES_PER_CHUNK,
) -> List[Dict[str, Any]]:
    image_map = {
        normalize_relative_image_path(str(image.get("img_path", ""))): image
        for image in document_images
        if isinstance(image, dict)
    }
    grouped_paths = chunk_image_run_groups(split_chunk_image_runs(chunk_content), group_size)
    chunk_images: List[Dict[str, Any]] = []

    for group_paths in grouped_paths:
        member_images = [image_map.get(relative_path) for relative_path in group_paths if image_map.get(relative_path)]
        member_images = [dict(image) for image in member_images if image]
        if not member_images:
            continue

        composite_local_path = compose_llm_image_group(cache_dir, group_paths, image_map)
        if not composite_local_path:
            continue

        caption_parts: List[str] = []
        for image in member_images:
            caption_parts.extend(
                str(item).strip() for item in image.get("image_caption", []) if str(item).strip()
            )
            caption_parts.extend(
                str(item).strip() for item in image.get("image_footnote", []) if str(item).strip()
            )

        chunk_images.append(
            {
                "img_path": " + ".join(group_paths),
                "local_path": composite_local_path,
                "page_idx": member_images[0].get("page_idx"),
                "image_caption": list(dict.fromkeys(caption_parts)),
                "image_footnote": [],
                "source_image_paths": group_paths,
                "source_local_paths": [image.get("local_path") for image in member_images if image.get("local_path")],
                "merged_image_count": len(member_images),
            }
        )
        if len(chunk_images) >= max_images:
            break

    return chunk_images


def build_review_excerpt_bundle(
    chunk_content: str, max_chars: int = REVIEW_EXCERPT_MAX_CHARS
) -> Dict[str, Any]:
    text_without_image_refs = strip_markdown_image_lines(chunk_content).strip()
    raw_image_ref_count = len(IMAGE_MARKDOWN_PATTERN.findall(chunk_content))
    caption_count = 0
    table_count = 0
    formula_count = 0

    for line in text_without_image_refs.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(("fig.", "fig ", "figure ", "table ")):
            caption_count += 1
        if "<table" in lowered or "</table>" in lowered or stripped.startswith("|"):
            table_count += 1
        if "$$" in stripped:
            formula_count += 1

    audit = {
        "raw_char_count": len(chunk_content),
        "raw_line_count": len(chunk_content.splitlines()),
        "raw_image_markdown_lines": count_markdown_image_lines(chunk_content),
        "removed_image_markdown_lines": raw_image_ref_count,
        "retained_heading_count": 0,
        "retained_caption_count": caption_count,
        "retained_table_count": table_count,
        "retained_keyword_count": 0,
        "retained_formula_count": formula_count,
        "llm_input_mode": "text-only",
        "image_binary_sent_to_llm": False,
        "input_strategy": "cleaned_full_chunk",
        "max_chars_ignored": max_chars,
    }

    audit["excerpt_char_count"] = len(text_without_image_refs)
    audit["excerpt_image_markdown_lines"] = count_markdown_image_lines(text_without_image_refs)
    audit["image_markdown_placeholders_sent_to_llm"] = bool(audit["excerpt_image_markdown_lines"])
    audit["figure_caption_text_sent_to_llm"] = bool(audit["retained_caption_count"])
    audit["table_markup_sent_to_llm"] = bool(audit["retained_table_count"])

    return {
        "text": text_without_image_refs,
        "audit": audit,
    }


def build_review_excerpt(chunk_content: str, max_chars: int = REVIEW_EXCERPT_MAX_CHARS) -> str:
    return build_review_excerpt_bundle(chunk_content, max_chars=max_chars)["text"]


def build_local_chunk_records(chunk: Chunk) -> List[Dict[str, Any]]:
    splitter = ChunkSplitter(
        min_size=LOCAL_CHUNK_MIN_SIZE,
        max_size=LOCAL_CHUNK_MAX_SIZE,
        logger=None,
    )
    local_chunks = splitter.split(chunk.content)
    records: List[Dict[str, Any]] = []

    for local_chunk in local_chunks:
        excerpt_bundle = build_review_excerpt_bundle(local_chunk.content)
        local_audit = dict(excerpt_bundle["audit"])
        local_audit["parent_chunk_id"] = chunk.id
        local_audit["local_chunk_id"] = local_chunk.id
        records.append(
            {
                "local_chunk_id": local_chunk.id,
                "review_excerpt": excerpt_bundle["text"],
                "current_chunk_text": strip_markdown_image_lines(local_chunk.content).strip(),
                "char_count": local_chunk.char_count,
                "review_audit": local_audit,
            }
        )

    if records:
        return records

    excerpt_bundle = build_review_excerpt_bundle(chunk.content)
    fallback_audit = dict(excerpt_bundle["audit"])
    fallback_audit["parent_chunk_id"] = chunk.id
    fallback_audit["local_chunk_id"] = 0
    return [
        {
            "local_chunk_id": 0,
            "review_excerpt": excerpt_bundle["text"],
            "current_chunk_text": strip_markdown_image_lines(chunk.content).strip(),
            "char_count": chunk.char_count,
            "review_audit": fallback_audit,
        }
    ]


def prefix_search_request_ids(search_requests: List[Dict[str, Any]], prefix: str) -> List[Dict[str, Any]]:
    renamed: List[Dict[str, Any]] = []
    for index, item in enumerate(search_requests or [], start=1):
        if not isinstance(item, dict):
            continue
        updated = deepcopy(item)
        original_request_id = str(updated.get("request_id", "") or "").strip() or str(index)
        updated["request_id"] = f"{prefix}-{original_request_id}"
        renamed.append(updated)
    return renamed


def aggregate_search_bundles(
    bundles: List[Dict[str, Any]],
    *,
    chunk_key: str = "local_chunk_id",
) -> Dict[str, Any]:
    combined = {
        "search_performed": False,
        "search_requests": [],
        "search_results": [],
        "subchunks": [],
    }

    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        search_performed = bool(bundle.get("search_performed"))
        combined["search_performed"] = combined["search_performed"] or search_performed
        combined["search_requests"].extend(deepcopy(bundle.get("search_requests", [])))
        combined["search_results"].extend(deepcopy(bundle.get("search_results", [])))
        combined["subchunks"].append(
            {
                chunk_key: bundle.get(chunk_key),
                "search_performed": search_performed,
                "search_request_count": len(bundle.get("search_requests", [])),
                "search_result_count": len(bundle.get("search_results", [])),
                "error": str(bundle.get("error", "") or "").strip(),
            }
        )

    return combined


def aggregate_llm_metrics(metrics_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    aggregate = {
        "llm_calls": 0,
        "elapsed_seconds": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    usage_sources = set()

    for metrics in metrics_list:
        if not isinstance(metrics, dict) or not metrics:
            continue
        aggregate["llm_calls"] += 1
        aggregate["elapsed_seconds"] += float(metrics.get("elapsed_seconds", 0.0) or 0.0)
        aggregate["prompt_tokens"] += int(metrics.get("prompt_tokens", 0) or 0)
        aggregate["completion_tokens"] += int(metrics.get("completion_tokens", 0) or 0)
        aggregate["total_tokens"] += int(metrics.get("total_tokens", 0) or 0)
        usage_source = str(metrics.get("usage_source", "") or "").strip()
        if usage_source:
            usage_sources.add(usage_source)

    aggregate["elapsed_seconds"] = round(aggregate["elapsed_seconds"], 3)
    aggregate["usage_source"] = ",".join(sorted(usage_sources)) if usage_sources else ""
    return aggregate


def summarize_review_audits(audits: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "chunks_audited": 0,
        "raw_image_markdown_lines": 0,
        "removed_image_markdown_lines": 0,
        "excerpt_image_markdown_lines": 0,
        "chunk_image_reference_count": 0,
        "chunk_image_input_count": 0,
        "retained_caption_count": 0,
        "retained_table_count": 0,
        "retained_formula_count": 0,
        "retained_keyword_count": 0,
        "image_binary_sent_to_llm": False,
        "image_markdown_placeholders_sent_to_llm": False,
        "figure_caption_text_sent_to_llm": False,
        "table_markup_sent_to_llm": False,
        "llm_input_mode": "text-only",
    }

    for audit in audits:
        if not isinstance(audit, dict):
            continue
        summary["chunks_audited"] += 1
        for key in (
            "raw_image_markdown_lines",
            "removed_image_markdown_lines",
            "excerpt_image_markdown_lines",
            "chunk_image_reference_count",
            "chunk_image_input_count",
            "retained_caption_count",
            "retained_table_count",
            "retained_formula_count",
            "retained_keyword_count",
        ):
            summary[key] += int(audit.get(key, 0) or 0)
        summary["image_binary_sent_to_llm"] = (
            summary["image_binary_sent_to_llm"] or bool(audit.get("image_binary_sent_to_llm"))
        )
        summary["image_markdown_placeholders_sent_to_llm"] = (
            summary["image_markdown_placeholders_sent_to_llm"]
            or bool(audit.get("image_markdown_placeholders_sent_to_llm"))
        )
        summary["figure_caption_text_sent_to_llm"] = (
            summary["figure_caption_text_sent_to_llm"]
            or bool(audit.get("figure_caption_text_sent_to_llm"))
        )
        summary["table_markup_sent_to_llm"] = (
            summary["table_markup_sent_to_llm"] or bool(audit.get("table_markup_sent_to_llm"))
        )
        if audit.get("llm_input_mode") == "text+image":
            summary["llm_input_mode"] = "text+image"

    return summary


def summarize_chunk_reading(audit: Dict[str, Any]) -> str:
    return (
        f"chunk={audit.get('excerpt_char_count', 0)} chars | "
        f"local_parts={audit.get('local_subchunk_count', 1)} | "
        f"images={audit.get('chunk_image_input_count', 0)} | "
        f"captions={audit.get('retained_caption_count', 0)} | "
        f"tables={audit.get('retained_table_count', 0)}"
    )


def summarize_chunk_completion(result_item: Dict[str, Any]) -> str:
    issues = result_item.get("issues", [])
    if not issues:
        return "0 个问题"

    labels = ", ".join(
        f"{issue.get('type', '?')}/{issue.get('severity', '?')}" for issue in issues[:3]
    )
    if len(issues) > 3:
        labels += ", ..."
    return f"{len(issues)} 个问题 | {labels}"


def summarize_language_switch(metadata: Dict[str, Any]) -> str:
    return (
        f"source={metadata.get('detected_language', 'unknown')} -> "
        f"target={metadata.get('target_language', 'unknown')} | "
        f"switch={metadata.get('switch_applied', False)} | "
        f"errors={metadata.get('translation_error_count', 0)} | "
        f"tok={metadata.get('total_tokens', 0)}"
    )


def normalize_text_list(value: Any) -> List[str]:
    items = value if isinstance(value, list) else [value]
    normalized: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def normalize_issue_evidence(value: Any) -> List[str]:
    return normalize_text_list(value)


def format_issue_evidence(value: Any) -> str:
    evidence_items = normalize_issue_evidence(value)
    return " | ".join(evidence_items) if evidence_items else "N/A"


def prepare_html_report_data(report_data: Dict[str, Any]) -> Dict[str, Any]:
    html_report = deepcopy(report_data)
    for issue in html_report.get("issues", []):
        if not isinstance(issue, dict):
            continue
        for field_name in ("evidence", "evidence_original", "location", "location_original"):
            if isinstance(issue.get(field_name), list):
                issue[field_name] = "\n".join(normalize_text_list(issue[field_name]))
    return html_report


def deduplicate_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()

    for issue in issues:
        fingerprint = (
            issue.get("type", ""),
            issue.get("description", ""),
            tuple(normalize_issue_evidence(issue.get("evidence", ""))),
            issue.get("chunk_id", ""),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(issue)

    return deduped


def merge_stage_issues_without_llm(*issue_lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fallback merger used when a later LLM stage times out."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for issue_list in issue_lists:
        for issue in issue_list or []:
            if not isinstance(issue, dict):
                continue
            candidate = deepcopy(issue)
            evidence = tuple(normalize_issue_evidence(candidate.get("evidence", [])))
            fingerprint = (
                str(candidate.get("type", "")).strip().lower(),
                str(candidate.get("description", "")).strip().lower(),
                str(candidate.get("location", "")).strip().lower(),
                evidence,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            merged.append(candidate)
    return merged


def prepare_chunk_review_input(
    *,
    index: int,
    chunk: Chunk,
    chunks: List[Chunk],
    document_overview: str,
    document_images: List[Dict[str, Any]],
    cache_dir: Path,
    logger: AgentLogger,
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    logger.progress(
        "Chunk Reading",
        chunk_id=chunk.id,
        status="heading",
        agent_name="Main",
        summary=f"char={chunk.char_count}",
    )
    logger.progress(
        "Chunk Reading",
        chunk_id=chunk.id,
        status="start",
        agent_name="Main",
        summary=f"原始长度={chunk.char_count} chars",
    )
    chunk_images: List[Dict[str, Any]] = []
    excerpt_bundle = build_review_excerpt_bundle(chunk.content)
    review_excerpt = excerpt_bundle["text"]
    review_audit = excerpt_bundle["audit"]
    review_audit["chunk_image_reference_count"] = len(IMAGE_MARKDOWN_PATTERN.findall(chunk.content))
    review_audit["chunk_image_input_count"] = len(chunk_images)
    review_audit["llm_input_mode"] = "text-only"
    review_audit["image_binary_sent_to_llm"] = False
    review_audit["image_paths_sent_to_llm"] = []
    local_chunk_records = build_local_chunk_records(chunk)
    review_audit["local_subchunk_count"] = len(local_chunk_records)
    explore_document_overview = build_explore_document_overview(document_overview, chunk.content)

    logger.log(
        "Main",
        "chunk_review_audit",
        chunk_id=chunk.id,
        data=review_audit,
        message="Prepared cleaned full chunk for LLM review",
    )
    logger.progress(
        "Chunk Reading",
        chunk_id=chunk.id,
        status="done",
        agent_name="Main",
        summary=summarize_chunk_reading(review_audit),
    )

    return {
        "chunk_id": chunk.id,
        "chunk_index": index,
        "review_excerpt": review_excerpt,
        "review_audit": review_audit,
        "chunk_images": chunk_images,
        "neighbor_context": build_neighbor_context(chunks, index),
        "current_chunk_text": strip_markdown_image_lines(chunk.content).strip(),
        "explore_document_overview": explore_document_overview,
        "local_chunk_records": local_chunk_records,
        "read_seconds": round(time.perf_counter() - started_at, 3),
    }


def process_chunk_plan(
    *,
    prepared_chunk: Dict[str, Any],
    logger: AgentLogger,
    cancel_check: Any = None,
) -> Dict[str, Any]:
    raise_if_review_cancelled(cancel_check)
    started_at = time.perf_counter()
    chunk_id = prepared_chunk["chunk_id"]
    with llm_cancel_context(cancel_check):
        plan_agent = PlanAgent(logger=logger)
        plan_output = plan_agent.analyze(
            prepared_chunk["review_excerpt"],
            chunk_id,
            image_inputs=prepared_chunk.get("chunk_images", []),
        )
    raise_if_review_cancelled(cancel_check)

    llm_metrics_list = [plan_output.get("_llm_metrics", {})]
    chunk_metrics = aggregate_llm_metrics(llm_metrics_list)
    chunk_metrics["wall_seconds"] = round(time.perf_counter() - started_at, 3)

    result = dict(prepared_chunk)
    result.update(
        {
            "plan_output": plan_output,
            "metrics": chunk_metrics,
            "llm_metrics_list": llm_metrics_list,
        }
    )
    return result


def run_chunk_vision_validation(
    *,
    issues: List[Dict[str, Any]],
    chunk_id: int,
    logger: AgentLogger,
    cache_dir: Path,
    pdf_path: str,
) -> List[Dict[str, Any]]:
    if not issues:
        return []

    screenshots_dir = resolve_agent_artifact_dir(
        logger=logger,
        subdir_key="vision_agent",
        cache_dir=cache_dir,
        fallback_name="vision_agent",
    ) / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    renderer = PDFIssueScreenshotRenderer(
        pdf_path,
        screenshots_dir,
        page_zoom=VISION_PAGE_ZOOM,
        crop_zoom=VISION_CROP_ZOOM,
        bbox_padding=VISION_BBOX_PADDING,
        max_matches=VISION_MAX_MATCH_IMAGES,
        bbox_normalized_size=BBOX_NORMALIZED_SIZE,
    )
    vision_agent = VisionValidationAgent(logger=logger)
    metrics_list: List[Dict[str, Any]] = []
    try:
        for issue_index, issue in enumerate(issues, start=1):
            screenshots = renderer.render_issue(issue, issue_index)
            validation = vision_agent.validate_issue(
                issue=issue,
                issue_index=issue_index,
                chunk_id=chunk_id,
                screenshots=screenshots,
            )
            llm_metrics = validation.pop("_llm_metrics", {})
            if llm_metrics:
                metrics_list.append(llm_metrics)
            issue["vision_validation"] = validation
            issue["vision_screenshots"] = [
                {
                    "kind": item.get("kind"),
                    "page": item.get("page"),
                    "bbox": item.get("bbox"),
                    "matched_text": item.get("matched_text"),
                    "local_path": item.get("local_path"),
                }
                for item in screenshots
            ]
    finally:
        renderer.close()

    return metrics_list


def run_chunk_recheck(
    *,
    issues: List[Dict[str, Any]],
    chunk_id: int,
    logger: AgentLogger,
    cache_dir: Path,
    pdf_path: str,
    full_document_text: str,
    current_chunk_text: str,
    text_enabled: bool,
    vision_enabled: bool,
) -> Dict[str, Any]:
    if not issues:
        return {
            "issues": [],
            "summary": {
                "enabled": bool(text_enabled or vision_enabled),
                "text_enabled": bool(text_enabled),
                "vision_enabled": bool(vision_enabled),
                "total_input_issues": 0,
                "text_validated_issues": 0,
                "vision_validated_issues": 0,
                "kept_issues": 0,
                "dropped_issues": 0,
                "review_issues": 0,
                "skipped_issues": 0,
            },
            "llm_metrics_list": [],
            "vision_metrics_list": [],
        }

    recheck_dir = resolve_agent_artifact_dir(
        logger=logger,
        subdir_key="recheck_agent",
        cache_dir=cache_dir,
        fallback_name="recheck_agent",
    )
    screenshots_dir = recheck_dir / "screenshots"
    agent = RecheckAgent(logger=logger)
    return agent.recheck_chunk(
        issues=issues,
        chunk_id=chunk_id,
        full_document_text=full_document_text,
        current_chunk_text=current_chunk_text,
        pdf_path=pdf_path,
        screenshots_dir=screenshots_dir,
        text_enabled=text_enabled,
        vision_enabled=vision_enabled,
    )


def run_stage_search(
    *,
    search_agent: Optional[SearchAgent],
    current_chunk: str,
    search_requests: List[Dict[str, Any]],
    chunk_id: int,
) -> Dict[str, Any]:
    normalized_requests = [item for item in search_requests if isinstance(item, dict)]
    empty_result = {
        "search_requests": normalized_requests,
        "search_results": [],
        "raw_search_results": [],
        "search_performed": False,
        "_llm_metrics": {},
    }

    if not normalized_requests:
        return empty_result
    if not search_agent or not search_agent.enabled:
        return empty_result

    try:
        search_result = search_agent.run_requests(
            current_chunk=current_chunk,
            search_requests=normalized_requests,
            chunk_id=chunk_id,
        )
    except TypeError as exc:
        if "current_chunk" not in str(exc):
            raise
        search_result = search_agent.run_requests(
            search_requests=normalized_requests,
            chunk_id=chunk_id,
        )
    return {
        "search_requests": normalized_requests,
        "search_results": list(search_result.get("search_results", [])),
        "raw_search_results": list(search_result.get("raw_search_results", [])),
        "search_performed": bool(search_result.get("search_performed", False)),
        "_llm_metrics": search_result.get("_llm_metrics", {}),
    }


def build_issue_search_result(
    *,
    source_stage: str,
    local_search_bundle: Dict[str, Any],
    global_search_bundle: Dict[str, Any],
) -> Dict[str, Any]:
    stage_name = str(source_stage or "").strip().lower()
    stage_payloads: List[Dict[str, Any]] = []

    def append_stage_payload(label: str, bundle: Dict[str, Any]) -> None:
        if not bundle.get("search_requests") and not bundle.get("search_results"):
            return
        stage_payloads.append(
            {
                "stage": label,
                "search_performed": bool(bundle.get("search_performed", False)),
                "search_requests": bundle.get("search_requests", []),
                "search_results": bundle.get("search_results", []),
            }
        )

    if stage_name in {"local", "local+global"}:
        append_stage_payload("local", local_search_bundle)
    if stage_name in {"global", "local+global"}:
        append_stage_payload("global", global_search_bundle)

    if not stage_payloads:
        return {}
    if len(stage_payloads) == 1:
        return stage_payloads[0]

    return {
        "search_performed": any(
            bool(item.get("search_performed", False)) for item in stage_payloads
        ),
        "stages": stage_payloads,
    }


def process_chunk_review(
    *,
    chunk_record: Dict[str, Any],
    document_overview: str,
    full_document_text: str,
    cache_dir: Path,
    logger: AgentLogger,
    vision_enabled: bool = False,
    search_enabled: bool = False,
    pdf_path: str = "",
    bbox_locator: Any = None,
    cancel_check: Any = None,
) -> Dict[str, Any]:
    raise_if_review_cancelled(cancel_check)
    started_at = time.perf_counter()
    chunk_id = int(chunk_record["chunk_id"])
    plan_output = chunk_record["plan_output"]
    review_excerpt = chunk_record["review_excerpt"]
    chunk_images = chunk_record.get("chunk_images", [])

    explore_agent = ExploreAgent(logger=logger)
    summary_agent = SummaryAgent(logger=logger)
    search_agent = SearchAgent(logger=logger, enabled=search_enabled) if search_enabled else None

    search_metrics_list: List[Dict[str, Any]] = []
    explore_metrics_list: List[Dict[str, Any]] = []
    plan_summary = str(plan_output.get("chunk_purpose", "") or "").strip()[:80] or "plan ready"
    local_chunk_records = chunk_record.get("local_chunk_records") or [
        {
            "local_chunk_id": 0,
            "review_excerpt": review_excerpt,
            "current_chunk_text": chunk_record.get("current_chunk_text") or review_excerpt,
            "char_count": len(str(review_excerpt or "").strip()),
            "review_audit": {},
        }
    ]
    global_document_overview = mark_current_chunk_in_document_overview(
        chunk_record.get("explore_document_overview") or document_overview,
        chunk_record.get("current_chunk_text") or review_excerpt,
    )
    anchored_document_overview = build_anchored_text(
        bbox_locator,
        global_document_overview,
        max_anchors=700,
    )
    anchored_current_chunk = build_anchored_text(
        bbox_locator,
        chunk_record.get("current_chunk_text") or review_excerpt,
        max_anchors=240,
    )

    logger.progress(
        "Local Check",
        chunk_id=chunk_id,
        status="start",
        level=1,
        agent_name="ExploreAgent",
        summary=f"{plan_summary} | parts={len(local_chunk_records)}",
    )
    local_result: List[Dict[str, Any]] = []
    local_search_bundles: List[Dict[str, Any]] = []
    local_stage_metrics: List[Dict[str, Any]] = []
    local_finalize_metrics: List[Dict[str, Any]] = []
    local_search_metrics: List[Dict[str, Any]] = []

    for local_index, local_chunk_record in enumerate(local_chunk_records):
        raise_if_review_cancelled(cancel_check)
        local_chunk_id = int(local_chunk_record.get("local_chunk_id", local_index) or local_index)
        local_review_excerpt = str(local_chunk_record.get("review_excerpt", "") or "").strip() or review_excerpt
        anchored_local_review_excerpt = build_anchored_text(
            bbox_locator,
            local_review_excerpt,
            max_anchors=100,
        )

        logger.log(
            "ExploreAgent",
            "stage_local_input",
            chunk_id=chunk_id,
            input_data={
                "plan_output": plan_output,
                "chunk_content": anchored_local_review_excerpt,
                "image_inputs": explore_agent._summarize_images(chunk_images),
                "local_chunk_id": local_chunk_id,
                "local_chunk_count": len(local_chunk_records),
            },
            message=f"Starting local check ({local_index + 1}/{len(local_chunk_records)})",
        )

        subchunk_result: List[Dict[str, Any]] = []
        subchunk_search_bundle: Dict[str, Any] = {
            "local_chunk_id": local_chunk_id,
            "search_performed": False,
            "search_requests": [],
            "search_results": [],
        }
        local_stage: Dict[str, Any] = {}
        local_finalize: Dict[str, Any] = {}
        try:
            with llm_cancel_context(cancel_check):
                local_stage = explore_agent.run_local_initial(
                    chunk_id=chunk_id,
                    chunk_content=anchored_local_review_excerpt,
                    plan_output=plan_output,
                    image_inputs=chunk_images,
                )
            raise_if_review_cancelled(cancel_check)
            subchunk_result = list(local_stage.get("local_error_list", []))
            if local_stage.get("_llm_metrics"):
                explore_metrics_list.append(local_stage["_llm_metrics"])
                local_stage_metrics.append(
                    {
                        "local_chunk_id": local_chunk_id,
                        "metrics": local_stage.get("_llm_metrics", {}),
                    }
                )

            renamed_search_requests = list(local_stage.get("search_requests", []))
            if len(local_chunk_records) > 1:
                renamed_search_requests = prefix_search_request_ids(
                    renamed_search_requests,
                    prefix=f"local-s{local_chunk_id + 1:02d}",
                )
            with llm_cancel_context(cancel_check):
                subchunk_search_bundle = run_stage_search(
                    search_agent=search_agent,
                    current_chunk=anchored_local_review_excerpt,
                    search_requests=renamed_search_requests,
                    chunk_id=chunk_id,
                )
            subchunk_search_bundle["local_chunk_id"] = local_chunk_id
            if subchunk_search_bundle.get("_llm_metrics"):
                search_metrics_list.append(subchunk_search_bundle["_llm_metrics"])
                local_search_metrics.append(
                    {
                        "local_chunk_id": local_chunk_id,
                        "metrics": subchunk_search_bundle.get("_llm_metrics", {}),
                    }
                )
            if subchunk_search_bundle.get("search_performed"):
                with llm_cancel_context(cancel_check):
                    local_finalize = explore_agent.run_local_finalize(
                        chunk_id=chunk_id,
                        chunk_content=anchored_local_review_excerpt,
                        plan_output=plan_output,
                        local_error_list=subchunk_result,
                        search_requests=subchunk_search_bundle.get("search_requests", []),
                        search_results=subchunk_search_bundle.get("search_results", []),
                        image_inputs=chunk_images,
                    )
                subchunk_result = list(local_finalize.get("local_error_list", []))
                if local_finalize.get("_llm_metrics"):
                    explore_metrics_list.append(local_finalize["_llm_metrics"])
                    local_finalize_metrics.append(
                        {
                            "local_chunk_id": local_chunk_id,
                            "metrics": local_finalize.get("_llm_metrics", {}),
                        }
                    )
        except (ReviewCancelled, LLMRequestCancelled):
            raise
        except Exception as exc:
            subchunk_search_bundle["error"] = str(exc)
            logger.log(
                "ExploreAgent",
                "stage_local_output_fallback",
                chunk_id=chunk_id,
                input_data={
                    "local_chunk_id": local_chunk_id,
                    "local_error_list": subchunk_result,
                    "search_requests": subchunk_search_bundle.get("search_requests", []),
                },
                output_data={
                    "local_chunk_id": local_chunk_id,
                    "local_error_list": subchunk_result,
                    "fallback_reason": f"Local subchunk exception: {exc}",
                },
                message=(
                    f"Local subchunk {local_index + 1}/{len(local_chunk_records)} "
                    f"did not complete; preserving {len(subchunk_result)} issues"
                ),
            )

        local_search_bundles.append(subchunk_search_bundle)
        local_result = merge_stage_issues_without_llm(local_result, subchunk_result)

    local_search_bundle = aggregate_search_bundles(local_search_bundles, chunk_key="local_chunk_id")

    logger.log(
        "ExploreAgent",
        "stage_local_output",
        chunk_id=chunk_id,
        data={
            "llm_metrics": {
                "local_initial": local_stage_metrics,
                "local_finalize": local_finalize_metrics,
                "search": local_search_metrics,
            }
        },
        output_data={
            "local_error_list": local_result,
            "search_requests": local_search_bundle.get("search_requests", []),
            "search_results": local_search_bundle.get("search_results", []),
            "local_chunk_count": len(local_chunk_records),
        },
        message=f"Local check produced {len(local_result)} issues across {len(local_chunk_records)} subchunks",
    )
    logger.progress(
        "Local Check",
        chunk_id=chunk_id,
        status="done",
        level=1,
        agent_name="ExploreAgent",
        summary=explore_agent._summarize_issues(local_result),
    )
    logger.progress(
        "Global Check",
        chunk_id=chunk_id,
        status="start",
        level=1,
        agent_name="ExploreAgent",
        summary=f"local={len(local_result)}",
    )

    raise_if_review_cancelled(cancel_check)
    global_stage: Dict[str, Any] = {}
    global_result: List[Dict[str, Any]] = []
    global_search_bundle: Dict[str, Any] = {
        "search_performed": False,
        "search_requests": [],
        "search_results": [],
    }
    global_finalize: Dict[str, Any] = {}
    try:
        with llm_cancel_context(cancel_check):
            global_stage = explore_agent.run_global_initial(
                chunk_id=chunk_id,
                document_overview=anchored_document_overview,
                image_inputs=chunk_images,
            )
        raise_if_review_cancelled(cancel_check)
        global_result = list(global_stage.get("global_error_list", []))
        with llm_cancel_context(cancel_check):
            global_search_bundle = run_stage_search(
                search_agent=search_agent,
                current_chunk=anchored_current_chunk,
                search_requests=global_stage.get("search_requests", []),
                chunk_id=chunk_id,
            )
        if global_stage.get("_llm_metrics"):
            explore_metrics_list.append(global_stage["_llm_metrics"])
        if global_search_bundle.get("_llm_metrics"):
            search_metrics_list.append(global_search_bundle["_llm_metrics"])
        if global_search_bundle.get("search_performed"):
            with llm_cancel_context(cancel_check):
                global_finalize = explore_agent.run_global_finalize(
                    chunk_id=chunk_id,
                    document_overview=anchored_document_overview,
                    global_error_list=global_result,
                    search_requests=global_search_bundle.get("search_requests", []),
                    search_results=global_search_bundle.get("search_results", []),
                    image_inputs=chunk_images,
                )
            global_result = list(global_finalize.get("global_error_list", []))
            if global_finalize.get("_llm_metrics"):
                explore_metrics_list.append(global_finalize["_llm_metrics"])
    except (ReviewCancelled, LLMRequestCancelled):
        raise
    except Exception as exc:
        global_search_bundle["error"] = str(exc)
        logger.log(
            "ExploreAgent",
            "stage_global_output_fallback",
            chunk_id=chunk_id,
            input_data={
                "document_overview": anchored_document_overview,
                "local_error_list": local_result,
            },
            output_data={
                "global_error_list": [],
                "preserved_local_error_list": local_result,
                "fallback_reason": f"Global check exception: {exc}",
            },
            message=f"Global check did not complete; preserving {len(local_result)} local issues",
        )

    logger.log(
        "ExploreAgent",
        "stage_global_output",
        chunk_id=chunk_id,
        data={
            "llm_metrics": {
                "global_initial": global_stage.get("_llm_metrics", {}),
                "global_finalize": global_finalize.get("_llm_metrics", {}) if global_search_bundle.get("search_performed") else {},
                "search": global_search_bundle.get("_llm_metrics", {}),
            }
        },
        output_data={
            "global_error_list": global_result,
            "search_requests": global_search_bundle.get("search_requests", []),
            "search_results": global_search_bundle.get("search_results", []),
        },
        message=f"Global check produced {len(global_result)} issues",
    )
    logger.progress(
        "Global Check",
        chunk_id=chunk_id,
        status="done",
        level=1,
        agent_name="ExploreAgent",
        summary=explore_agent._summarize_issues(global_result),
    )
    merge_stage: Dict[str, Any] = {}
    if search_enabled:
        logger.progress(
            "Finalize ErrorList",
            chunk_id=chunk_id,
            status="start",
            level=1,
            agent_name="ExploreAgent",
            summary=f"local={len(local_result)} | global={len(global_result)}",
        )

        raise_if_review_cancelled(cancel_check)
        try:
            with llm_cancel_context(cancel_check):
                merge_stage = explore_agent.merge_error_lists(
                    chunk_id=chunk_id,
                    plan_output=plan_output,
                    local_error_list=local_result,
                    global_error_list=global_result,
                    image_inputs=chunk_images,
                )
            final_result = list(merge_stage.get("error_list", []))
            if merge_stage.get("_llm_metrics"):
                explore_metrics_list.append(merge_stage["_llm_metrics"])
        except (ReviewCancelled, LLMRequestCancelled):
            raise
        except Exception as exc:
            final_result = merge_stage_issues_without_llm(local_result, global_result)
            merge_stage = {
                "error_list": final_result,
                "_llm_metrics": {"fallback": True, "error": str(exc)},
            }
            explore_metrics_list.append(merge_stage["_llm_metrics"])
            logger.log(
                "ExploreAgent",
                "stage_final_output_fallback",
                chunk_id=chunk_id,
                input_data={
                    "local_error_list": local_result,
                    "global_error_list": global_result,
                },
                output_data={
                    "error_list": final_result,
                    "fallback_reason": f"Merge exception: {exc}",
                },
                message=f"Merge did not complete; using {len(final_result)} staged issues without LLM merge",
            )

        logger.log(
            "ExploreAgent",
            "stage_final_output",
            chunk_id=chunk_id,
            data={"llm_metrics": merge_stage.get("_llm_metrics", {})},
            output_data={"error_list": final_result},
            message=f"Final ErrorList contains {len(final_result)} issues",
        )
        logger.progress(
            "Finalize ErrorList",
            chunk_id=chunk_id,
            status="done",
            level=1,
            agent_name="ExploreAgent",
            summary=explore_agent._summarize_issues(final_result),
        )
    else:
        final_result = merge_stage_issues_without_llm(local_result, global_result)
        merge_stage = {
            "error_list": final_result,
            "_llm_metrics": {},
            "skipped": True,
            "reason": "search_disabled",
        }
        logger.log(
            "ExploreAgent",
            "stage_final_output",
            chunk_id=chunk_id,
            data={"llm_metrics": {}, "skipped": True, "reason": "search_disabled"},
            output_data={"error_list": final_result},
            message=f"Skipped final merge because search is disabled; keeping {len(final_result)} staged issues",
        )
        logger.progress(
            "Finalize ErrorList",
            chunk_id=chunk_id,
            status="done",
            level=1,
            agent_name="ExploreAgent",
            summary=f"skipped | {explore_agent._summarize_issues(final_result)}",
        )

    explore_output = {
        "local_error_list": local_result,
        "global_error_list": global_result,
        "final_error_list": final_result,
        "error_list": final_result,
        "local_search_requests": local_search_bundle.get("search_requests", []),
        "global_search_requests": global_search_bundle.get("search_requests", []),
        "local_search_results": local_search_bundle.get("search_results", []),
        "global_search_results": global_search_bundle.get("search_results", []),
        "_llm_metrics_list": explore_metrics_list,
    }

    candidate_issues = []
    for issue in explore_output.get("final_error_list", []):
        issue_with_chunk = deepcopy(issue)
        issue_with_chunk["chunk_id"] = chunk_id
        issue_with_chunk["search_result"] = build_issue_search_result(
            source_stage=str(issue.get("source_stage", "") or ""),
            local_search_bundle=local_search_bundle,
            global_search_bundle=global_search_bundle,
        )
        candidate_issues.append(issue_with_chunk)

    if bbox_locator:
        for issue in candidate_issues:
            bbox_lookup = bbox_locator.locate_issue(issue, max_matches=BBOX_MATCH_LIMIT)
            issue.update(bbox_lookup)

    raise_if_review_cancelled(cancel_check)
    with llm_cancel_context(cancel_check):
        summary_output = summary_agent.summarize(
            chunk_id=chunk_id,
            plan_output=plan_output,
            explore_output=explore_output,
            candidate_issues=candidate_issues,
        )
    raise_if_review_cancelled(cancel_check)
    issues = []
    recheck_text_enabled = bool(vision_enabled and RECHECK_LLM_ENABLED)
    recheck_vision_enabled = bool(vision_enabled and RECHECK_VLM_ENABLED)
    recheck_enabled = bool(recheck_text_enabled or recheck_vision_enabled)
    for issue in summary_output.get("issues", []):
        issue["chunk_id"] = chunk_id
        ensure_issue_review_defaults(
            issue,
            vision_enabled=recheck_vision_enabled,
            text_enabled=recheck_text_enabled,
        )
        issues.append(issue)

    recheck_metrics_list: List[Dict[str, Any]] = []
    vision_metrics_list: List[Dict[str, Any]] = []
    recheck_summary: Dict[str, Any] = {
        "enabled": recheck_enabled,
        "text_enabled": recheck_text_enabled,
        "vision_enabled": recheck_vision_enabled,
        "total_input_issues": len(issues),
        "text_validated_issues": 0,
        "vision_validated_issues": 0,
        "kept_issues": 0,
        "dropped_issues": 0,
        "review_issues": 0,
        "skipped_issues": len(issues),
    }
    if issues and recheck_enabled:
        raise_if_review_cancelled(cancel_check)
        try:
            with llm_cancel_context(cancel_check):
                recheck_result = run_chunk_recheck(
                    issues=issues,
                    chunk_id=chunk_id,
                    logger=logger,
                    cache_dir=cache_dir,
                    pdf_path=pdf_path,
                    full_document_text=full_document_text,
                    current_chunk_text=chunk_record.get("current_chunk_text") or review_excerpt,
                    text_enabled=recheck_text_enabled,
                    vision_enabled=recheck_vision_enabled,
                )
            issues = list(recheck_result.get("issues", issues))
            recheck_summary = dict(recheck_result.get("summary", recheck_summary))
            recheck_metrics_list = list(recheck_result.get("llm_metrics_list", []))
            vision_metrics_list = list(recheck_result.get("vision_metrics_list", []))
        except (ReviewCancelled, LLMRequestCancelled):
            raise
        except Exception as exc:
            logger.log(
                "RecheckAgent",
                "chunk_output_fallback",
                chunk_id=chunk_id,
                input_data={"issues": issues},
                output_data={"issues": issues, "error": str(exc)},
                message=f"Recheck failed; preserving {len(issues)} summarized issues",
            )
    elif not recheck_enabled:
        recheck_summary["reason"] = "Recheck optional models are not configured for this mode."

    llm_metrics_list = (
        chunk_record.get("llm_metrics_list", [])
        + list(explore_output.get("_llm_metrics_list", []))
        + search_metrics_list
        + [summary_output.get("_llm_metrics", {})]
        + recheck_metrics_list
    )
    chunk_metrics = aggregate_llm_metrics(llm_metrics_list)
    chunk_metrics["wall_seconds"] = round(time.perf_counter() - started_at, 3)

    return {
        "chunk_id": chunk_id,
        "issues": issues,
        "metrics": chunk_metrics,
        "review_audit": chunk_record.get("review_audit"),
        "llm_metrics_list": llm_metrics_list,
        "vision_metrics_list": vision_metrics_list,
        "recheck_summary": recheck_summary,
        "plan_output": plan_output,
        "explore_output": explore_output,
    }


def run_review(
    pdf_path: str,
    *,
    mode: str = "standard",
    report_language: str = REPORT_LANGUAGE,
    html_enabled: bool = REPORT_HTML_ENABLED,
    vision_enabled: Optional[bool] = None,
    search_enabled: Optional[bool] = None,
    progress_callback: Any = None,
    log_callback: Any = None,
    partial_result_callback: Any = None,
    resume_state: Optional[Dict[str, Any]] = None,
    cancel_check: Any = None,
) -> Dict[str, Any]:
    raise_if_review_cancelled(cancel_check)
    run_started_at = time.perf_counter()
    mode = normalize_review_mode(mode)
    mode_features = resolve_review_mode_features(mode)
    if vision_enabled is None:
        vision_enabled = mode_features["vision_enabled"]
    if search_enabled is None:
        search_enabled = mode_features["search_enabled"]
    report_language = normalize_report_language(report_language)
    logger = AgentLogger(live_callback=log_callback)

    # Wrap progress_callback to also call it when progress is made
    _original_callback = progress_callback
    def progress_with_callback(phase: str, percent: int, message: str, **kwargs):
        if _original_callback:
            _original_callback({"phase": phase, "percent": percent, **kwargs}, message)

    logger.log(
        "Main",
        "start",
        data={
            "pdf_path": pdf_path,
            "mode": mode,
            "report_language": report_language,
            "html_enabled": html_enabled,
            "vision_enabled": bool(vision_enabled),
            "search_enabled": bool(search_enabled),
        },
        message="Starting paper review",
    )
    progress_with_callback("PDF 解析", 5, "开始解析PDF...")
    logger.progress("PDF 解析", status="start", agent_name="Main")
    raise_if_review_cancelled(cancel_check)

    cache_dir = get_cache_dir(pdf_path)
    md_file = cache_dir / f"{Path(pdf_path).stem}_markdown.md"

    parse_started_at = time.perf_counter()
    if md_file.exists():
        logger.log("Main", "cache_hit", data={"cache_dir": str(cache_dir)}, message="Loading cached parse result")
        parse_result = load_cached_parse_result(pdf_path, logger=logger)
        if needs_parser_backend_refresh(parse_result):
            logger.log(
                "Main",
                "cache_parser_backend_miss",
                data={
                    "cached_backend": getattr(parse_result, "parser_backend", "unknown"),
                    "active_backend": "mineru",
                },
                message="Cached parse backend differs from current parser; refreshing parse cache",
            )
            parser = PDFParser(logger=logger)
            parse_result = parser.parse(pdf_path)
            cache_dir = save_parse_result(pdf_path, parse_result)
            logger.log("Main", "cache_saved", data={"cache_dir": str(cache_dir)}, message="Saved parse cache")
        elif needs_multimodal_asset_refresh(parse_result):
            logger.log(
                "Main",
                "cache_image_miss",
                data={
                    "cached_images": len(parse_result.images),
                    "available_local_images": count_available_local_images(parse_result.images),
                },
                message="Cached parse is missing local image assets; refreshing PDF parse cache",
            )
            parser = PDFParser(logger=logger)
            parse_result = parser.parse(pdf_path)
            cache_dir = save_parse_result(pdf_path, parse_result)
            logger.log("Main", "cache_saved", data={"cache_dir": str(cache_dir)}, message="Saved parse cache")
        elif needs_cached_artifact_refresh(pdf_path, parse_result):
            cache_dir = save_parse_result(pdf_path, parse_result)
            logger.log(
                "Main",
                "cache_refreshed",
                data={"cache_dir": str(cache_dir)},
                message="Refreshed derived cache artifacts from local parser outputs",
            )
    else:
        logger.log("Main", "parse_start", data={"pdf_path": pdf_path}, message="Parsing PDF")
        parser = PDFParser(logger=logger)
        parse_result = parser.parse(pdf_path)

        if parse_result and (parse_result.markdown or parse_result.images or parse_result.bbox_json):
            cache_dir = save_parse_result(pdf_path, parse_result)
            logger.log("Main", "cache_saved", data={"cache_dir": str(cache_dir)}, message="Saved parse cache")

    if not parse_result:
        raise ValueError("Failed to obtain a parse result")

    raise_if_review_cancelled(cancel_check)
    parse_elapsed = time.perf_counter() - parse_started_at
    markdown_content = parse_result.markdown
    logger.log(
        "Main",
        "parse_complete",
        data={
            "markdown_length": len(markdown_content),
            "elapsed_seconds": round(parse_elapsed, 3),
        },
        message=f"PDF parsing completed with {len(markdown_content)} markdown characters",
    )
    logger.progress(
        "PDF 解析",
        status="done",
        agent_name="Main",
        summary=(
            f"markdown={len(markdown_content)} | images={len(parse_result.images)} | "
            f"bbox={'yes' if parse_result.bbox_json else 'no'}"
        ),
    )

    available_local_image_count = count_available_local_images(parse_result.images)
    document_assets = {
        "parser_backend": getattr(parse_result, "parser_backend", "unknown"),
        "parser_image_count": len(parse_result.images),
        "mineru_image_count": len(parse_result.images),
        "available_local_image_count": available_local_image_count,
        "markdown_image_markdown_count": count_markdown_image_lines(markdown_content),
        "has_bbox_json": bool(parse_result.bbox_json),
        "bbox_page_count": count_bbox_pages(parse_result.bbox_json),
        "llm_input_mode": "text-only",
        "image_binary_sent_to_llm": False,
    }
    logger.log(
        "Main",
        "document_assets",
        data=document_assets,
        message="Audited parsed image and bbox artifacts",
    )

    chunk_started_at = time.perf_counter()
    logger.progress("Chunk 划分", status="start", agent_name="Main")
    logger.log(
        "Main",
        "chunk_start",
        data={"markdown_length": len(markdown_content)},
        message="Starting chunking",
    )
    splitter = ChunkSplitter(logger=logger)
    chunks = splitter.split(markdown_content)
    raise_if_review_cancelled(cancel_check)
    chunk_elapsed = time.perf_counter() - chunk_started_at
    logger.log(
        "Main",
        "chunk_complete",
        data={
            "chunk_count": len(chunks),
            "elapsed_seconds": round(chunk_elapsed, 3),
        },
        message=f"Chunking completed with {len(chunks)} chunks",
    )
    logger.progress(
        "Chunk 划分",
        status="done",
        agent_name="Main",
        summary=f"{len(chunks)} 个 chunks | llm_mode={document_assets['llm_input_mode']}",
    )
    progress_with_callback("Chunk 划分", 30, f"完成 {len(chunks)} 个 chunk 划分")

    logger.save_chunks(chunks)

    # Create bbox_locator before chunk processing for per-chunk VisionAgent
    bbox_locator = BBoxLocator(parse_result.bbox_json, parse_result.images)

    full_document_text = strip_markdown_image_lines(markdown_content).strip()
    document_overview = build_document_overview(markdown_content)
    resume_state = resume_state if isinstance(resume_state, dict) else {}
    resumed_chunk_ids = [
        chunk_id
        for chunk_id in normalize_chunk_id_list(resume_state.get("completed_chunk_ids"))
        if chunk_id < len(chunks)
    ]
    resumed_chunk_id_set = set(resumed_chunk_ids)
    resumed_issues: List[Dict[str, Any]] = []
    for issue in resume_state.get("issues", []):
        if not isinstance(issue, dict):
            continue
        try:
            chunk_id = int(issue.get("chunk_id"))
        except (TypeError, ValueError):
            continue
        if chunk_id not in resumed_chunk_id_set:
            continue
        resumed_issues.append(deepcopy(issue))

    if resumed_chunk_ids:
        logger.log(
            "Main",
            "resume_loaded",
            data={
                "resumed_chunk_ids": resumed_chunk_ids,
                "resumed_chunk_count": len(resumed_chunk_ids),
                "remaining_chunk_count": len(chunks) - len(resumed_chunk_ids),
            },
            output_data={"resumed_issue_count": len(resumed_issues)},
            message=f"Resuming review from {len(resumed_chunk_ids)} completed chunks",
        )

    all_issues: List[Dict[str, Any]] = list(resumed_issues)
    llm_call_metrics: List[Dict[str, Any]] = []
    vision_llm_metrics: List[Dict[str, Any]] = []
    chunk_audits: List[Dict[str, Any]] = []
    review_started_at = time.perf_counter()

    def emit_partial_result(collected_results: List[Dict[str, Any]]) -> None:
        if not callable(partial_result_callback):
            return

        partial_issues: List[Dict[str, Any]] = list(resumed_issues)
        for item in sorted(collected_results, key=lambda value: value.get("chunk_id", 0)):
            partial_issues.extend(item.get("issues", []))

        partial_issues = deduplicate_issues(partial_issues)
        processed_chunk_ids = sorted(
            resumed_chunk_id_set.union(
                int(item.get("chunk_id"))
                for item in collected_results
                if item.get("chunk_id") is not None
            )
        )
        partial_result_callback(
            {
                "pdf_path": pdf_path,
                "total_chunks": len(chunks),
                "processed_chunks": len(processed_chunk_ids),
                "processed_chunk_ids": processed_chunk_ids,
                "total_issues": len(partial_issues),
                "issues": partial_issues,
                "vision_rejected_issues": [
                    issue
                    for issue in partial_issues
                    if get_issue_review_decision(issue) == "drop"
                ],
                "bbox_summary": {
                    "issues_with_bbox": sum(1 for issue in partial_issues if issue.get("bbox_lookup_resolved")),
                    "total_issues": len(partial_issues),
                },
                "report_language": report_language,
                "is_partial": True,
            }
        )

    tasks = [(index, chunk) for index, chunk in enumerate(chunks) if chunk.id not in resumed_chunk_id_set]

    for index, chunk in tasks:
        raise_if_review_cancelled(cancel_check)
        logger.log(
            "Main",
            "chunk_processing",
            chunk_id=chunk.id,
            input_data={"chunk_preview": chunk.content[:200] + "..."},
            message=f"Processing chunk {chunk.id}",
        )

    parallelism = max(1, min(REVIEW_PARALLELISM, len(chunks)))

    logger.progress("Chunk 规划", status="start", agent_name="Main")
    if parallelism == 1:
        planned_chunks = []
        for index, chunk in tasks:
            raise_if_review_cancelled(cancel_check)
            prepared = prepare_chunk_review_input(
                index=index,
                chunk=chunk,
                chunks=chunks,
                document_overview=document_overview,
                document_images=parse_result.images,
                cache_dir=cache_dir,
                logger=logger,
            )
            planned_chunks.append(
                    process_chunk_plan(
                        prepared_chunk=prepared,
                        logger=logger,
                        cancel_check=cancel_check,
                    )
            )
    else:
        prepared_chunks = []
        for index, chunk in tasks:
            raise_if_review_cancelled(cancel_check)
            prepared_chunks.append(
                prepare_chunk_review_input(
                    index=index,
                    chunk=chunk,
                    chunks=chunks,
                    document_overview=document_overview,
                    document_images=parse_result.images,
                    cache_dir=cache_dir,
                    logger=logger,
                )
            )
        planned_chunks = []
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            future_map = {
                executor.submit(
                    process_chunk_plan,
                    prepared_chunk=prepared_chunk,
                    logger=logger,
                    cancel_check=cancel_check,
                ): prepared_chunk["chunk_id"]
                for prepared_chunk in prepared_chunks
            }
            for future in as_completed(future_map):
                raise_if_review_cancelled(cancel_check)
                chunk_id = future_map[future]
                try:
                    planned_chunks.append(future.result())
                except (ReviewCancelled, LLMRequestCancelled):
                    raise
                except Exception as exc:
                    logger.log(
                        "Main",
                        "chunk_plan_error",
                        chunk_id=chunk_id,
                        message=f"Chunk {chunk_id} plan failed: {exc}",
                    )
                    raise
    logger.progress(
        "Chunk 规划",
        status="done",
        agent_name="Main",
        summary=f"{len(planned_chunks)} 个 chunks",
    )
    progress_with_callback("Chunk 规划", 45, f"完成 {len(planned_chunks)} 个 chunk 规划")

    if parallelism == 1:
        results = []
        for chunk_record in sorted(planned_chunks, key=lambda item: item["chunk_id"]):
            raise_if_review_cancelled(cancel_check)
            results.append(
                process_chunk_review(
                    chunk_record=chunk_record,
                    document_overview=document_overview,
                    full_document_text=full_document_text,
                    cache_dir=cache_dir,
                    logger=logger,
                    vision_enabled=vision_enabled,
                    search_enabled=search_enabled,
                    pdf_path=pdf_path,
                    bbox_locator=bbox_locator,
                    cancel_check=cancel_check,
                )
            )
            emit_partial_result(results)
    else:
        results = []
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            future_map = {
                executor.submit(
                    process_chunk_review,
                    chunk_record=chunk_record,
                    document_overview=document_overview,
                    full_document_text=full_document_text,
                    cache_dir=cache_dir,
                    logger=logger,
                    vision_enabled=vision_enabled,
                    search_enabled=search_enabled,
                    pdf_path=pdf_path,
                    bbox_locator=bbox_locator,
                    cancel_check=cancel_check,
                ): chunk_record["chunk_id"]
                for chunk_record in planned_chunks
            }
            for future in as_completed(future_map):
                raise_if_review_cancelled(cancel_check)
                chunk_id = future_map[future]
                try:
                    results.append(future.result())
                    emit_partial_result(results)
                except (ReviewCancelled, LLMRequestCancelled):
                    raise
                except Exception as exc:
                    logger.log(
                        "Main",
                        "chunk_error",
                        chunk_id=chunk_id,
                        message=f"Chunk {chunk_id} failed: {exc}",
                    )
                    results.append({"chunk_id": chunk_id, "issues": []})

    for result_item in sorted(results, key=lambda item: item["chunk_id"]):
        raise_if_review_cancelled(cancel_check)
        all_issues.extend(result_item["issues"])
        llm_call_metrics.extend(result_item.get("llm_metrics_list", []))
        vision_llm_metrics.extend(result_item.get("vision_metrics_list", []))
        if result_item.get("review_audit"):
            chunk_audits.append(result_item["review_audit"])
        logger.log(
            "Main",
            "chunk_complete",
            chunk_id=result_item["chunk_id"],
            output_data={
                "issues_found": len(result_item["issues"]),
                "metrics": result_item.get("metrics", {}),
            },
            message=f"Completed chunk {result_item['chunk_id']}",
        )
        logger.progress(
            "Chunk 检测",
            chunk_id=result_item["chunk_id"],
            status="done",
            agent_name="Main",
            summary=summarize_chunk_completion(result_item),
        )

    progress_with_callback("Chunk 检测", 65, f"完成 {len(chunks)} 个 chunk 检测")
    all_issues = deduplicate_issues(all_issues)

    # BBox enrichment is already done per-chunk in process_chunk_review, skip here

    logger.progress("BBox 截图调试", status="start", agent_name="Main")
    bbox_debug_result = save_bbox_debug_screenshots(
        issues=all_issues,
        pdf_path=pdf_path,
        logger=logger,
        enabled=SAVE_BBOX_DEBUG_SCREENSHOTS,
    )
    all_issues = bbox_debug_result["issues"]
    bbox_debug_summary = bbox_debug_result["summary"]
    logger.progress(
        "BBox 截图调试",
        status="done",
        agent_name="Main",
        summary=summarize_bbox_debug(bbox_debug_summary),
    )
    progress_with_callback("BBox 截图调试", 80, f"完成 {len(all_issues)} 个问题的截图调试")

    vision_elapsed = 0.0
    vision_stage_enabled = bool(vision_enabled and RECHECK_VLM_ENABLED)
    vision_summary = {
        "enabled": vision_stage_enabled,
        "total_input_issues": len(all_issues),
        "validated_issues": 0,
        "kept_issues": 0,
        "dropped_issues": 0,
        "review_issues": 0,
        "skipped_issues": 0,
        "llm_metrics_list": vision_llm_metrics,
    }
    if not vision_stage_enabled:
        vision_summary["reason"] = "Vision agent is not configured for this mode."
    else:
        for issue in all_issues:
            decision = str(issue.get("vision_validation", {}).get("decision", "skip") or "skip").strip().lower()
            if decision != "skip":
                vision_summary["validated_issues"] += 1
            if decision == "drop":
                vision_summary["dropped_issues"] += 1
            elif decision == "review":
                vision_summary["review_issues"] += 1
                vision_summary["kept_issues"] += 1
            elif decision == "keep":
                vision_summary["kept_issues"] += 1
            else:
                vision_summary["skipped_issues"] += 1
    logger.progress(
        "Vision 裁决",
        status="done",
        agent_name="Main",
        summary=summarize_vision_validation(vision_summary) if vision_stage_enabled else "Vision disabled",
    )
    progress_with_callback(
        "Vision 裁决",
        85,
        "已完成 per-chunk Vision 验证" if vision_stage_enabled else "Vision optional stage skipped",
    )

    recheck_text_enabled = bool(vision_enabled and RECHECK_LLM_ENABLED)
    recheck_vision_enabled = bool(vision_enabled and RECHECK_VLM_ENABLED)
    recheck_summary = {
        "enabled": bool(recheck_text_enabled or recheck_vision_enabled),
        "text_enabled": recheck_text_enabled,
        "vision_enabled": recheck_vision_enabled,
        "total_input_issues": len(all_issues),
        "text_validated_issues": 0,
        "vision_validated_issues": vision_summary["validated_issues"],
        "kept_issues": 0,
        "dropped_issues": 0,
        "review_issues": 0,
        "skipped_issues": 0,
    }
    if not recheck_summary["enabled"]:
        recheck_summary["reason"] = "Recheck optional models are not configured for this mode."
    for issue in all_issues:
        text_decision = str(issue.get("text_validation", {}).get("decision", "skip") or "skip").strip().lower()
        if text_decision != "skip":
            recheck_summary["text_validated_issues"] += 1

        decision = get_issue_review_decision(issue)
        if decision == "drop":
            recheck_summary["dropped_issues"] += 1
        elif decision == "review":
            recheck_summary["review_issues"] += 1
        elif decision == "keep":
            recheck_summary["kept_issues"] += 1
        else:
            recheck_summary["skipped_issues"] += 1

    review_elapsed = time.perf_counter() - review_started_at
    bbox_resolved_count = sum(1 for issue in all_issues if issue.get("bbox_lookup_resolved"))

    llm_metrics = aggregate_llm_metrics(llm_call_metrics)
    llm_metrics["llm_elapsed_seconds"] = llm_metrics.pop("elapsed_seconds", 0.0)
    overall_metrics = {
        "parse_seconds": round(parse_elapsed, 3),
        "chunk_seconds": round(chunk_elapsed, 3),
        "review_seconds": round(review_elapsed, 3),
        "vision_seconds": vision_elapsed,
        **llm_metrics,
    }
    overall_metrics["review_llm_calls"] = overall_metrics["llm_calls"]
    overall_metrics["review_prompt_tokens"] = overall_metrics["prompt_tokens"]
    overall_metrics["review_completion_tokens"] = overall_metrics["completion_tokens"]
    overall_metrics["review_total_tokens"] = overall_metrics["total_tokens"]
    overall_metrics["language_switch_seconds"] = 0.0
    overall_metrics["language_switch_calls"] = 0
    overall_metrics["language_switch_tokens"] = 0
    overall_metrics["recheck_calls"] = int(recheck_summary.get("text_validated_issues", 0) or 0)
    overall_metrics["vision_calls"] = int(vision_summary.get("validated_issues", 0) or 0)
    overall_metrics["vision_tokens"] = sum(
        int(metrics.get("total_tokens", 0) or 0)
        for metrics in vision_llm_metrics
        if isinstance(metrics, dict)
    )
    overall_metrics["html_report_seconds"] = 0.0
    review_audit_summary = summarize_review_audits(chunk_audits)
    multimodal_audit = {
        **document_assets,
        **review_audit_summary,
        "images_really_sent_to_llm": bool(review_audit_summary.get("image_binary_sent_to_llm")),
        "images_sent_as_binary": bool(review_audit_summary.get("image_binary_sent_to_llm")),
    }
    bbox_summary = {
        "bbox_lookup_enabled": bool(bbox_locator.candidates),
        "bbox_candidates": len(bbox_locator.candidates),
        "issues_with_bbox": bbox_resolved_count,
        "total_issues": len(all_issues),
    }

    logger.log(
        "Main",
        "metrics",
        data=overall_metrics,
        message="Collected review timing and token estimates",
    )
    logger.progress(
        "结果保存",
        status="done",
        agent_name="Main",
        summary=(
            f"issues={len(all_issues)} | tok={overall_metrics['review_total_tokens']} | "
            f"review={overall_metrics['review_seconds']}s"
        ),
    )
    base_result = {
        "pdf_path": pdf_path,
        "total_chunks": len(chunks),
        "processed_chunks": len(chunks),
        "processed_chunk_ids": [chunk.id for chunk in chunks],
        "total_issues": len(all_issues),
        "issues": all_issues,
        "vision_rejected_issues": [
            i for i in all_issues
            if get_issue_review_decision(i) == "drop"
        ],
        "metrics": overall_metrics,
        "multimodal_audit": multimodal_audit,
        "bbox_summary": bbox_summary,
        "bbox_debug_summary": bbox_debug_summary,
        "vision_summary": vision_summary,
        "recheck_summary": recheck_summary,
        "logs_dir": str(logger.get_session_dir()),
        "report_language": report_language,
        "is_partial": False,
    }

    raw_result = deepcopy(base_result)
    raw_report_path = logger.save_review_report(raw_result, filename="review_report.raw.json")

    raise_if_review_cancelled(cancel_check)
    logger.progress("语言切换", status="start", agent_name="Main")
    language_switch_started_at = time.perf_counter()
    language_switch_agent = ReportLanguageSwitchAgent(target_language=report_language, logger=logger)
    try:
        with llm_cancel_context(cancel_check):
            result, language_switch_metadata = language_switch_agent.switch_report(base_result)
    except (ReviewCancelled, LLMRequestCancelled):
        raise
    except Exception as exc:
        result = deepcopy(base_result)
        result["report_language"] = report_language
        language_switch_metadata = {
            "target_language": report_language,
            "switch_applied": False,
            "translated_issue_count": 0,
            "translation_error_count": 1,
            "fallback": True,
            "error": str(exc),
            "llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        result["language_switch"] = language_switch_metadata
        logger.log(
            "LanguageSwitchAgent",
            "translation_error",
            data={"error_type": type(exc).__name__},
            output_data={"error": str(exc)},
            message="Language switch failed; preserving untranslated report",
        )
    raise_if_review_cancelled(cancel_check)
    overall_metrics["language_switch_seconds"] = round(time.perf_counter() - language_switch_started_at, 3)
    overall_metrics["language_switch_calls"] = int(language_switch_metadata.get("llm_calls", 0) or 0)
    overall_metrics["language_switch_tokens"] = int(language_switch_metadata.get("total_tokens", 0) or 0)
    overall_metrics["prompt_tokens"] += int(language_switch_metadata.get("prompt_tokens", 0) or 0)
    overall_metrics["completion_tokens"] += int(language_switch_metadata.get("completion_tokens", 0) or 0)
    overall_metrics["total_tokens"] += int(language_switch_metadata.get("total_tokens", 0) or 0)
    overall_metrics["llm_calls"] += int(language_switch_metadata.get("llm_calls", 0) or 0)
    logger.progress(
        "语言切换",
        status="done",
        agent_name="Main",
        summary=summarize_language_switch(language_switch_metadata),
    )

    html_report_path = ""
    if html_enabled:
        raise_if_review_cancelled(cancel_check)
        logger.progress("HTML 报告生成", status="start", agent_name="Main")
        html_started_at = time.perf_counter()
        html_content = render_review_report_html(prepare_html_report_data(result), markdown_content)
        saved_html_path = logger.save_review_html(html_content)
        html_report_path = str(saved_html_path)
        overall_metrics["html_report_seconds"] = round(time.perf_counter() - html_started_at, 3)
        logger.log(
            "ReportRenderer",
            "output",
            data={
                "html_path": html_report_path,
                "issue_count": result.get("total_issues", 0),
                "report_language": result.get("report_language", report_language),
            },
            message="Rendered HTML review report",
        )
        logger.progress(
            "HTML 报告生成",
            status="done",
            agent_name="Main",
            summary=Path(html_report_path).name,
        )
        progress_with_callback("HTML 报告生成", 95, "报告生成完成")

    overall_metrics["wall_seconds"] = round(time.perf_counter() - run_started_at, 3)
    result["metrics"] = overall_metrics
    result["report_files"] = {
        "raw_json": str(raw_report_path),
        "final_json": str(logger.subdirs["review_report"] / "review_report.json"),
        "html": html_report_path,
    }

    logger.log(
        "Main",
        "complete",
        data={
            "total_issues": len(all_issues),
            "metrics": overall_metrics,
            "bbox_summary": bbox_summary,
            "report_language": result.get("report_language", report_language),
            "html_report_path": html_report_path,
        },
        message=f"Review completed with {len(all_issues)} issues",
    )
    logger.save_review_report(result)
    logger.save_index()

    progress_with_callback("完成", 100, f"审查完成，发现 {len(all_issues)} 个问题")

    return result


def configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            reconfigure(errors="replace")


def safe_print(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sanitized = str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(sanitized)


def main() -> None:
    configure_console_output()
    parser = argparse.ArgumentParser(description="DraftClaw academic paper review")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--output", "-o", help="Optional JSON output path", default=None)
    parser.add_argument("--no-cache", action="store_true", help="Re-parse the PDF instead of using cache")
    parser.add_argument(
        "--report-language",
        choices=["zh", "en"],
        default=normalize_report_language(REPORT_LANGUAGE),
        help="Language used for the final review report and HTML output",
    )
    parser.add_argument(
        "--mode",
        choices=["fast", "standard", "deep"],
        default="standard",
        help="Review mode that controls vision and search stages",
    )
    parser.add_argument(
        "--no-html-report",
        action="store_true",
        help="Skip HTML report generation",
    )
    vision_group = parser.add_mutually_exclusive_group()
    vision_group.add_argument(
        "--disable-vision-agent",
        action="store_true",
        help="Skip the Vision Agent verification stage",
    )
    vision_group.add_argument(
        "--enable-vision-agent",
        action="store_true",
        help="Force-enable the Vision Agent verification stage",
    )

    args = parser.parse_args()
    pdf_path = Path(args.pdf_path)

    if not pdf_path.exists():
        print(f"Error: file does not exist: {pdf_path}")
        sys.exit(1)

    if args.no_cache:
        cache_dir = get_cache_dir(str(pdf_path))
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            print(f"Removed cache directory: {cache_dir}")

    mode = normalize_review_mode(args.mode)
    mode_features = resolve_review_mode_features(mode)
    vision_enabled = mode_features["vision_enabled"]
    search_enabled = mode_features["search_enabled"]
    if args.disable_vision_agent:
        vision_enabled = False
    elif args.enable_vision_agent:
        vision_enabled = True

    try:
        result = run_review(
            str(pdf_path),
            mode=mode,
            report_language=args.report_language,
            html_enabled=not args.no_html_report,
            vision_enabled=vision_enabled,
            search_enabled=search_enabled,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as file_handle:
                json.dump(result, file_handle, ensure_ascii=False, indent=2)

        safe_print("\n" + "=" * 60)
        safe_print("DraftClaw Review Report")
        safe_print("=" * 60)
        safe_print(f"PDF: {result['pdf_path']}")
        safe_print(f"Chunks: {result['total_chunks']}")
        safe_print(f"Issues: {result['total_issues']}")
        safe_print(f"Wall time: {result['metrics']['wall_seconds']}s")
        safe_print(f"Estimated tokens: {result['metrics']['total_tokens']}")
        safe_print(f"Report language: {result.get('report_language', args.report_language)}")
        safe_print(
            "Image payload to LLM: "
            f"{result['multimodal_audit']['llm_input_mode']} "
            f"(binary={result['multimodal_audit']['images_sent_as_binary']})"
        )
        safe_print(
            "BBox matched issues: "
            f"{result['bbox_summary']['issues_with_bbox']}/{result['bbox_summary']['total_issues']}"
        )
        if result.get("bbox_debug_summary"):
            safe_print(
                "BBox debug screenshots: "
                f"{result['bbox_debug_summary'].get('saved_screenshots', 0)} "
                f"(coord=normalized_{result['bbox_debug_summary'].get('bbox_normalized_size', 1000)})"
            )
        if result.get("vision_summary"):
            if not result["vision_summary"].get("enabled", False):
                safe_print("Vision validation: disabled")
            else:
                safe_print(
                    "Vision validation: "
                    f"kept={result['vision_summary'].get('kept_issues', 0)} "
                    f"dropped={result['vision_summary'].get('dropped_issues', 0)} "
                    f"review={result['vision_summary'].get('review_issues', 0)} "
                    f"skipped={result['vision_summary'].get('skipped_issues', 0)}"
                )
        safe_print("=" * 60)

        for index, issue in enumerate(result["issues"], start=1):
            safe_print(f"\n[{index}] {issue.get('type', 'unknown')} ({issue.get('severity', 'unknown')})")
            safe_print(f"    Chunk: {issue.get('chunk_id', 'N/A')}")
            safe_print(f"    Description: {issue.get('description', 'N/A')}")
            safe_print(f"    Evidence: {format_issue_evidence(issue.get('evidence', 'N/A'))}")

        safe_print(f"\nLogs saved to: {result['logs_dir']}")
        if result.get("report_files", {}).get("html"):
            safe_print(f"HTML report written to: {result['report_files']['html']}")

        if args.output:
            safe_print(f"Full report written to: {args.output}")
    except Exception as exc:
        print(f"Error: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
