"""
PDF parsing through MinerU with cache persistence helpers.
"""

import json
import os
import re
import shutil
import statistics
import time
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import requests
from config import (
    CACHE_DIR,
    MINERU_API_KEY,
    MINERU_API_URL,
)
from logger import AgentLogger
from bbox_locator import build_bbox_debug_markdown, build_content_list_v2_bbox_index


MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"


class PDFParseResult:
    """Container for parsed PDF artifacts."""

    def __init__(
        self,
        markdown: str = "",
        images: Optional[List[Dict[str, Any]]] = None,
        bbox_json: Optional[Dict[str, Any]] = None,
        image_assets: Optional[Dict[str, bytes]] = None,
        raw_json_entries: Optional[Dict[str, Any]] = None,
        archive_entries: Optional[List[str]] = None,
        source_entries: Optional[Dict[str, str]] = None,
        parser_backend: str = "",
    ):
        self.markdown = markdown
        self.images = images or []
        self.bbox_json = bbox_json or {}
        self.image_assets = image_assets or {}
        self.raw_json_entries = raw_json_entries or {}
        self.archive_entries = archive_entries or []
        self.source_entries = source_entries or {}
        self.parser_backend = parser_backend or "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "markdown": self.markdown,
            "images": self.images,
            "bbox_json": self.bbox_json,
            "raw_json_entry_names": sorted(self.raw_json_entries.keys()),
            "archive_entry_count": len(self.archive_entries),
            "parser_backend": self.parser_backend,
        }


class PDFParser:
    """Parse a PDF through MinerU."""

    def __init__(self, logger: Optional[AgentLogger] = None):
        self.api_url = MINERU_API_URL.rstrip("/")
        self.api_key = MINERU_API_KEY
        self.logger = logger
        self.session = requests.Session()

    def parse(self, pdf_path: str) -> PDFParseResult:
        if self.logger:
            self.logger.log(
                "PDFParser",
                "input",
                data={"pdf_path": pdf_path, "backend": "mineru"},
                message="Starting PDF parse",
            )

        if MOCK_MODE:
            result = PDFParseResult()
            if self.logger:
                self.logger.log("PDFParser", "output", data={"mock": True}, message="MOCK mode enabled")
            return result

        return self._parse_with_mineru(pdf_path)

    def _parse_with_mineru(self, pdf_path: str) -> PDFParseResult:
        if not self.api_key:
            raise ValueError("MINERU_API_KEY is not configured")

        try:
            batch_id, file_urls = self._get_upload_urls(pdf_path)
            if not file_urls:
                raise ValueError("MinerU did not return an upload URL")

            self._upload_file(pdf_path, file_urls[0])
            parse_result = self._get_parse_result(batch_id)

            if self.logger:
                self.logger.log(
                    "PDFParser",
                    "output",
                    data={
                        "backend": "mineru",
                        "markdown_length": len(parse_result.markdown),
                        "image_count": len(parse_result.images),
                        "has_bbox": bool(parse_result.bbox_json),
                    },
                    message="PDF parse completed",
                )

            return parse_result
        except Exception as exc:
            if self.logger:
                self.logger.log("PDFParser", "error", message=f"PDF parse failed: {exc}")
            raise

    def _get_upload_urls(self, pdf_path: str) -> Tuple[str, List[str]]:
        url = f"{self.api_url}/file-urls/batch"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        pdf_name = Path(pdf_path).name
        payload = {
            "files": [{"name": pdf_name, "data_id": pdf_name}],
            "model_version": "vlm",
        }

        if self.logger:
            self.logger.log(
                "PDFParser",
                "get_upload_url",
                data={"url": url, "file_name": pdf_name},
                message="Requesting upload URL",
            )

        response = self.session.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()

        if self.logger:
            self.logger.log(
                "PDFParser",
                "get_upload_url_response",
                data={"response": result},
                message="Received upload URL response",
            )

        if result.get("code") != 0:
            raise ValueError(f"Failed to get upload URL: {result.get('msg')}")

        data = result.get("data", {})
        return data["batch_id"], data["file_urls"]

    def _upload_file(self, pdf_path: str, upload_url: str) -> None:
        if self.logger:
            self.logger.log("PDFParser", "upload_file", data={"url": upload_url}, message="Uploading PDF")

        with open(pdf_path, "rb") as file_handle:
            response = self.session.put(upload_url, data=file_handle, timeout=120)

        if self.logger:
            self.logger.log(
                "PDFParser",
                "upload_file_response",
                data={"status": response.status_code},
                message="Upload completed",
            )

        if response.status_code != 200:
            raise ValueError(f"File upload failed: {response.status_code}")

    def _get_parse_result(
        self, batch_id: str, max_wait: int = 300, poll_interval: int = 5
    ) -> PDFParseResult:
        url = f"{self.api_url}/extract-results/batch/{batch_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        if self.logger:
            self.logger.log(
                "PDFParser",
                "poll_result",
                data={"batch_id": batch_id, "url": url},
                message="Polling MinerU batch result",
            )

        for attempt in range(max_wait // poll_interval):
            response = self.session.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            result = response.json()

            if self.logger:
                self.logger.log(
                    "PDFParser",
                    "poll_response",
                    data={"attempt": attempt, "result": result},
                    message="Received poll response",
                )

            if result.get("code") != 0:
                raise ValueError(f"MinerU poll failed: {result.get('msg')}")

            items = result.get("data", {}).get("extract_result", [])
            item = items[0] if items else {}
            state = item.get("state", "")

            if state == "done":
                zip_url = item.get("full_zip_url")
                if not zip_url:
                    raise ValueError("MinerU result is done but full_zip_url is missing")
                return self._download_parse_bundle(zip_url)

            if state == "failed":
                error_message = item.get("err_msg") or "unknown MinerU error"
                raise ValueError(f"MinerU parse failed: {error_message}")

            time.sleep(poll_interval)

        raise TimeoutError(f"MinerU parse timed out after {max_wait} seconds")

    def _download_parse_bundle(self, zip_url: str) -> PDFParseResult:
        if self.logger:
            self.logger.log(
                "PDFParser",
                "download_bundle",
                data={"url": zip_url},
                message="Downloading MinerU result bundle",
            )

        response = self.session.get(zip_url, timeout=120)
        response.raise_for_status()

        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            names = archive.namelist()
            markdown_entry = self._find_entry(names, lambda name: name.endswith("full.md"))
            content_list_entry = self._find_entry(names, lambda name: name.endswith("_content_list.json"))
            content_list_v2_entry = self._find_entry(names, lambda name: name.endswith("content_list_v2.json"))
            layout_entry = self._find_entry(names, lambda name: name.endswith("layout.json"))
            markdown = self._read_text_entry(archive, markdown_entry)
            raw_json_entries = self._read_json_entries(archive, names)
            content_list = raw_json_entries.get(content_list_entry, {}) if content_list_entry else {}
            content_list_v2 = raw_json_entries.get(content_list_v2_entry, {}) if content_list_v2_entry else {}
            layout = raw_json_entries.get(layout_entry, {}) if layout_entry else {}
            image_assets = self._read_image_assets(archive, names)

        images: List[Dict[str, Any]] = []
        if isinstance(content_list, list):
            images = [
                item
                for item in content_list
                if isinstance(item, dict) and item.get("type") == "image"
            ]

        bbox_json: Dict[str, Any] | List[Any] = {}
        if isinstance(content_list_v2, list):
            bbox_json = build_content_list_v2_bbox_index(content_list_v2)
        elif isinstance(layout, dict):
            bbox_json = layout
        elif isinstance(content_list, list):
            bbox_json = {"content_list": content_list}

        return PDFParseResult(
            markdown=markdown,
            images=images,
            bbox_json=bbox_json,
            image_assets=image_assets,
            raw_json_entries=raw_json_entries,
            archive_entries=names,
            source_entries={
                "markdown_entry": markdown_entry or "",
                "content_list_entry": content_list_entry or "",
                "content_list_v2_entry": content_list_v2_entry or "",
                "layout_entry": layout_entry or "",
            },
            parser_backend="mineru",
        )

    @staticmethod
    def _find_entry(names: List[str], predicate) -> Optional[str]:
        for name in names:
            if predicate(name):
                return name
        return None

    @staticmethod
    def _read_text_entry(archive: zipfile.ZipFile, name: Optional[str]) -> str:
        if not name:
            return ""
        return archive.read(name).decode("utf-8", errors="replace")

    @staticmethod
    def _read_json_entry(archive: zipfile.ZipFile, name: Optional[str]) -> Any:
        if not name:
            return {}
        return json.loads(archive.read(name).decode("utf-8"))

    @staticmethod
    def _read_json_entries(archive: zipfile.ZipFile, names: List[str]) -> Dict[str, Any]:
        entries: Dict[str, Any] = {}
        for name in names:
            if not name.endswith(".json") or name.endswith("/"):
                continue
            try:
                entries[name] = json.loads(archive.read(name).decode("utf-8"))
            except json.JSONDecodeError:
                continue
        return entries

    @staticmethod
    def _read_image_assets(archive: zipfile.ZipFile, names: List[str]) -> Dict[str, bytes]:
        assets: Dict[str, bytes] = {}
        for name in names:
            if name.endswith("/"):
                continue
            normalized_name = normalize_relative_asset_path(name)
            if not normalized_name.startswith("images/"):
                continue
            assets[normalized_name] = archive.read(name)
        return assets


def normalize_relative_asset_path(path_value: str) -> str:
    normalized = str(path_value).replace("\\", "/").strip()
    if "images/" in normalized:
        normalized = normalized[normalized.index("images/") :]
    return normalized.lstrip("/")


FIGURE_CAPTION_PATTERN = re.compile(r"^(Figure\s+\d+)\s*:\s*(.+)$", re.IGNORECASE)
IMAGE_REFERENCE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
IMAGE_LINE_PATTERN = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")
SUBCAPTION_PATTERN = re.compile(r"^\([a-zA-Z]\)(?:\s+.*)?$")


def normalize_archive_entry_path(path_value: str) -> Path:
    parts = [part for part in PurePosixPath(path_value).parts if part not in ("", ".", "..")]
    return Path(*parts)


def attach_local_image_paths(cache_dir: Path, images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    attached: List[Dict[str, Any]] = []
    transient_keys = {
        "figure_group_id",
        "figure_label",
        "figure_caption",
        "figure_subcaptions",
        "figure_member_count",
        "figure_group_bbox",
        "figure_member_paths",
        "is_subfigure",
        "composite_local_path",
    }
    for item in images:
        if not isinstance(item, dict):
            continue
        image_item = {key: value for key, value in item.items() if key not in transient_keys}
        relative_path = normalize_relative_asset_path(str(image_item.get("img_path", "")))
        if relative_path:
            local_path = cache_dir / relative_path
            if local_path.exists():
                image_item["local_path"] = str(local_path.resolve())
            image_item["img_path"] = relative_path
        attached.append(image_item)
    return attached


def build_image_asset_manifest(
    cache_dir: Path, image_assets: Dict[str, bytes], images: List[Dict[str, Any]], markdown: str
) -> List[Dict[str, Any]]:
    markdown_paths = {
        normalize_relative_asset_path(match)
        for match in IMAGE_REFERENCE_PATTERN.findall(markdown)
        if normalize_relative_asset_path(match)
    }
    image_entry_paths = {
        normalize_relative_asset_path(str(item.get("img_path", "")))
        for item in images
        if isinstance(item, dict)
    }
    manifest: List[Dict[str, Any]] = []
    asset_paths = {
        normalize_relative_asset_path(path_value)
        for path_value in image_assets.keys()
        if normalize_relative_asset_path(path_value)
    }
    if not asset_paths:
        asset_paths = {
            image_path.relative_to(cache_dir).as_posix()
            for image_path in (cache_dir / "images").rglob("*")
            if image_path.is_file()
        }

    for relative_path in sorted(
        asset_paths
    ):
        local_path = cache_dir / relative_path
        manifest.append(
            {
                "relative_path": relative_path,
                "local_path": str(local_path.resolve()) if local_path.exists() else "",
                "file_size": local_path.stat().st_size if local_path.exists() else 0,
                "referenced_in_markdown": relative_path in markdown_paths,
                "referenced_in_content_list_image_items": relative_path in image_entry_paths,
            }
        )

    return manifest


def resolve_bbox_json(
    raw_json_entries: Dict[str, Any],
    source_entries: Dict[str, str],
    fallback_bbox_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    content_list_v2_entry = str(source_entries.get("content_list_v2_entry", "")).strip()
    content_list_v2 = raw_json_entries.get(content_list_v2_entry)
    if isinstance(content_list_v2, list):
        return build_content_list_v2_bbox_index(content_list_v2)
    return dict(fallback_bbox_json or {})


def save_bbox_debug_markdown(cache_dir: Path, pdf_name: str, bbox_json: Dict[str, Any]) -> None:
    if not isinstance(bbox_json, dict) or bbox_json.get("source") != "content_list_v2":
        return
    debug_path = cache_dir / f"{pdf_name}_bbox_debug.md"
    with open(debug_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(build_bbox_debug_markdown(bbox_json))


def extract_markdown_figure_groups(markdown: str) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    pending_paths: List[str] = []
    pending_subcaptions: List[str] = []
    lines = markdown.splitlines()
    i = 0

    def flush_pending(caption: str = "", figure_label: str = "") -> None:
        nonlocal pending_paths, pending_subcaptions
        if not pending_paths:
            return
        image_paths = list(dict.fromkeys(pending_paths))
        group_number = len(groups) + 1
        group_id = figure_label.lower().replace(" ", "_") if figure_label else f"figure_group_{group_number:03d}"
        groups.append(
            {
                "figure_group_id": group_id,
                "figure_label": figure_label,
                "figure_caption": caption,
                "subcaptions": list(pending_subcaptions),
                "image_paths": image_paths,
            }
        )
        pending_paths = []
        pending_subcaptions = []

    while i < len(lines):
        stripped = lines[i].strip()
        image_match = IMAGE_LINE_PATTERN.match(stripped)
        if image_match:
            relative_path = normalize_relative_asset_path(image_match.group(1))
            if relative_path:
                pending_paths.append(relative_path)
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        if pending_paths and SUBCAPTION_PATTERN.match(stripped):
            pending_subcaptions.append(stripped)
            i += 1
            continue

        if pending_paths:
            caption_match = FIGURE_CAPTION_PATTERN.match(stripped)
            if caption_match:
                caption_lines = [stripped]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if not next_line:
                        break
                    if IMAGE_LINE_PATTERN.match(next_line) or next_line.startswith("Table "):
                        break
                    if FIGURE_CAPTION_PATTERN.match(next_line):
                        break
                    caption_lines.append(next_line)
                    j += 1
                flush_pending(caption=" ".join(caption_lines), figure_label=caption_match.group(1))
                i = j
                continue

            flush_pending()

        i += 1

    flush_pending()
    return groups


def union_bboxes(items: List[List[Any]]) -> List[float]:
    valid_boxes = [
        bbox
        for bbox in items
        if isinstance(bbox, list) and len(bbox) >= 4 and all(isinstance(value, (int, float)) for value in bbox[:4])
    ]
    if not valid_boxes:
        return []
    return [
        min(bbox[0] for bbox in valid_boxes),
        min(bbox[1] for bbox in valid_boxes),
        max(bbox[2] for bbox in valid_boxes),
        max(bbox[3] for bbox in valid_boxes),
    ]


def build_figure_groups(markdown: str, images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    image_map = {
        normalize_relative_asset_path(str(item.get("img_path", ""))): item
        for item in images
        if isinstance(item, dict)
    }
    figure_groups: List[Dict[str, Any]] = []

    for group in extract_markdown_figure_groups(markdown):
        member_images: List[Dict[str, Any]] = []
        for image_path in group["image_paths"]:
            image_item = image_map.get(image_path)
            if not image_item:
                continue
            member_images.append(
                {
                    "img_path": image_item.get("img_path", image_path),
                    "local_path": image_item.get("local_path", ""),
                    "bbox": image_item.get("bbox", []),
                    "page_idx": image_item.get("page_idx"),
                    "raw_image_caption": image_item.get("image_caption", []),
                    "raw_image_footnote": image_item.get("image_footnote", []),
                }
            )

        figure_groups.append(
            {
                "figure_group_id": group["figure_group_id"],
                "figure_label": group["figure_label"],
                "figure_caption": group["figure_caption"],
                "subcaptions": group["subcaptions"],
                "image_paths": group["image_paths"],
                "local_paths": [item["local_path"] for item in member_images if item.get("local_path")],
                "page_indices": sorted(
                    {
                        item.get("page_idx")
                        for item in member_images
                        if isinstance(item.get("page_idx"), int)
                    }
                ),
                "group_bbox": union_bboxes([item.get("bbox", []) for item in member_images]),
                "member_count": len(member_images),
                "member_images": member_images,
            }
        )

    return figure_groups


def annotate_images_with_figure_groups(
    images: List[Dict[str, Any]], figure_groups: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    group_by_image_path: Dict[str, Dict[str, Any]] = {}
    for group in figure_groups:
        for image_path in group.get("image_paths", []):
            group_by_image_path[normalize_relative_asset_path(image_path)] = group

    annotated: List[Dict[str, Any]] = []
    for item in images:
        if not isinstance(item, dict):
            continue
        image_item = dict(item)
        relative_path = normalize_relative_asset_path(str(image_item.get("img_path", "")))
        group = group_by_image_path.get(relative_path)
        if group:
            image_item["figure_group_id"] = group.get("figure_group_id", "")
            image_item["figure_label"] = group.get("figure_label", "")
            image_item["figure_caption"] = group.get("figure_caption", "")
            image_item["figure_subcaptions"] = group.get("subcaptions", [])
            image_item["figure_member_count"] = group.get("member_count", 0)
            image_item["figure_group_bbox"] = group.get("group_bbox", [])
            image_item["figure_member_paths"] = group.get("image_paths", [])
            image_item["is_subfigure"] = group.get("member_count", 0) > 1
        annotated.append(image_item)

    return annotated


def save_raw_mineru_json_entries(
    cache_dir: Path,
    raw_json_entries: Dict[str, Any],
    archive_entries: List[str],
    source_entries: Dict[str, str],
) -> None:
    raw_dir = cache_dir / "mineru_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for relative_name, json_payload in raw_json_entries.items():
        raw_path = raw_dir / normalize_archive_entry_path(relative_name)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as file_handle:
            json.dump(json_payload, file_handle, ensure_ascii=False, indent=2)

    manifest_path = cache_dir / f"{cache_dir.name.replace('_files', '')}_mineru_bundle_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as file_handle:
        json.dump(
            {
                "archive_entries": archive_entries,
                "json_entries": sorted(raw_json_entries.keys()),
                "source_entries": source_entries,
                "raw_json_cache_dir": str(raw_dir.resolve()),
            },
            file_handle,
            ensure_ascii=False,
            indent=2,
        )


def save_raw_parser_json_entries(
    cache_dir: Path,
    raw_json_entries: Dict[str, Any],
    archive_entries: List[str],
    source_entries: Dict[str, str],
    parser_backend: str,
) -> None:
    raw_dir = cache_dir / "parser_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for relative_name, json_payload in raw_json_entries.items():
        raw_path = raw_dir / normalize_archive_entry_path(relative_name)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as file_handle:
            json.dump(json_payload, file_handle, ensure_ascii=False, indent=2)

    manifest_path = cache_dir / f"{cache_dir.name.replace('_files', '')}_parse_bundle_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as file_handle:
        json.dump(
            {
                "parser_backend": parser_backend,
                "archive_entries": archive_entries,
                "json_entries": sorted(raw_json_entries.keys()),
                "source_entries": source_entries,
                "raw_json_cache_dir": str(raw_dir.resolve()),
            },
            file_handle,
            ensure_ascii=False,
            indent=2,
        )


def compose_figure_image(cache_dir: Path, figure_group: Dict[str, Any]) -> str:
    member_images = figure_group.get("member_images", [])
    if not member_images:
        return ""
    figures_dir = cache_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    output_path = figures_dir / f"{figure_group.get('figure_group_id', 'figure')}.jpg"
    if len(member_images) == 1:
        source_path = Path(member_images[0].get("local_path", ""))
        if not source_path.exists():
            return ""
        shutil.copyfile(source_path, output_path)
        return str(output_path.resolve())

    try:
        from PIL import Image
    except ImportError:
        return ""

    drawable_members = []
    scale_candidates: List[float] = []
    for member in member_images:
        local_path = member.get("local_path")
        bbox = member.get("bbox", [])
        if not local_path or not Path(local_path).exists():
            continue
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        bbox_width = max(float(bbox[2]) - float(bbox[0]), 1.0)
        bbox_height = max(float(bbox[3]) - float(bbox[1]), 1.0)
        with Image.open(local_path) as source_image:
            rendered = source_image.convert("RGB")
        scale_candidates.extend([rendered.width / bbox_width, rendered.height / bbox_height])
        drawable_members.append((rendered, bbox))

    if not drawable_members:
        return ""

    group_bbox = figure_group.get("group_bbox", [])
    if not group_bbox or len(group_bbox) < 4:
        return ""
    scale = statistics.median(candidate for candidate in scale_candidates if candidate > 0) if scale_candidates else 1.0
    scale = max(1.0, min(scale, 8.0))
    canvas_width = max(int(round((group_bbox[2] - group_bbox[0]) * scale)), 1)
    canvas_height = max(int(round((group_bbox[3] - group_bbox[1]) * scale)), 1)
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")

    for rendered, bbox in drawable_members:
        target_width = max(int(round((bbox[2] - bbox[0]) * scale)), 1)
        target_height = max(int(round((bbox[3] - bbox[1]) * scale)), 1)
        target_x = int(round((bbox[0] - group_bbox[0]) * scale))
        target_y = int(round((bbox[1] - group_bbox[1]) * scale))
        resized = rendered.resize((target_width, target_height), Image.Resampling.LANCZOS)
        canvas.paste(resized, (target_x, target_y))

    canvas.save(output_path, quality=95)
    return str(output_path.resolve())


def save_parse_result(pdf_path: str, result: PDFParseResult):
    """Persist parse artifacts in the local cache."""

    pdf_name = Path(pdf_path).stem
    cache_dir = CACHE_DIR / f"{pdf_name}_files"
    cache_dir.mkdir(parents=True, exist_ok=True)

    md_path = cache_dir / f"{pdf_name}_markdown.md"
    with open(md_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(result.markdown)

    for relative_path, image_bytes in result.image_assets.items():
        asset_path = cache_dir / normalize_relative_asset_path(relative_path)
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        with open(asset_path, "wb") as file_handle:
            file_handle.write(image_bytes)

    figures_dir = cache_dir / "figures"
    if figures_dir.exists():
        shutil.rmtree(figures_dir)
    figures_path = cache_dir / f"{pdf_name}_figures.json"
    if figures_path.exists():
        figures_path.unlink()

    result.images = attach_local_image_paths(cache_dir, result.images)
    result.bbox_json = resolve_bbox_json(
        result.raw_json_entries,
        result.source_entries,
        fallback_bbox_json=result.bbox_json if isinstance(result.bbox_json, dict) else {},
    )

    img_path = cache_dir / f"{pdf_name}_images.json"
    with open(img_path, "w", encoding="utf-8") as file_handle:
        json.dump(result.images, file_handle, ensure_ascii=False, indent=2)

    bbox_path = cache_dir / f"{pdf_name}_bbox.json"
    with open(bbox_path, "w", encoding="utf-8") as file_handle:
        json.dump(result.bbox_json, file_handle, ensure_ascii=False, indent=2)
    save_bbox_debug_markdown(cache_dir, pdf_name, result.bbox_json)

    asset_manifest = build_image_asset_manifest(cache_dir, result.image_assets, result.images, result.markdown)
    asset_manifest_path = cache_dir / f"{pdf_name}_image_assets.json"
    with open(asset_manifest_path, "w", encoding="utf-8") as file_handle:
        json.dump(asset_manifest, file_handle, ensure_ascii=False, indent=2)

    save_raw_parser_json_entries(
        cache_dir,
        raw_json_entries=result.raw_json_entries,
        archive_entries=result.archive_entries,
        source_entries=result.source_entries,
        parser_backend=result.parser_backend,
    )

    return cache_dir


def load_cached_parse_result(
    pdf_path: str, logger: Optional[AgentLogger] = None
) -> Optional[PDFParseResult]:
    """Load a cached parse result if one exists."""

    pdf_name = Path(pdf_path).stem
    cache_dir = CACHE_DIR / f"{pdf_name}_files"

    md_path = cache_dir / f"{pdf_name}_markdown.md"
    if not md_path.exists():
        return None

    if logger:
        logger.log(
            "PDFParser",
            "cache_load",
            data={"pdf_path": pdf_path, "cache_dir": str(cache_dir)},
            input_data={"cache_source": str(md_path)},
            message="Loading cached parse result",
        )

    with open(md_path, "r", encoding="utf-8") as file_handle:
        markdown = file_handle.read()

    img_path = cache_dir / f"{pdf_name}_images.json"
    images = []
    if img_path.exists():
        with open(img_path, "r", encoding="utf-8") as file_handle:
            images = json.load(file_handle)
        images = attach_local_image_paths(cache_dir, images)

    bbox_path = cache_dir / f"{pdf_name}_bbox.json"
    bbox_json = {}
    if bbox_path.exists():
        with open(bbox_path, "r", encoding="utf-8") as file_handle:
            bbox_json = json.load(file_handle)

    raw_json_entries: Dict[str, Any] = {}
    raw_dir = cache_dir / "parser_raw"
    legacy_raw_dir = cache_dir / "mineru_raw"
    active_raw_dir = raw_dir if raw_dir.exists() else legacy_raw_dir
    if active_raw_dir.exists():
        for raw_path in active_raw_dir.rglob("*.json"):
            relative_name = raw_path.relative_to(active_raw_dir).as_posix()
            with open(raw_path, "r", encoding="utf-8") as file_handle:
                raw_json_entries[relative_name] = json.load(file_handle)

    manifest_path = cache_dir / f"{pdf_name}_parse_bundle_manifest.json"
    legacy_manifest_path = cache_dir / f"{pdf_name}_mineru_bundle_manifest.json"
    archive_entries: List[str] = []
    source_entries: Dict[str, str] = {}
    parser_backend = "unknown"
    active_manifest_path = manifest_path if manifest_path.exists() else legacy_manifest_path
    if active_manifest_path.exists():
        with open(active_manifest_path, "r", encoding="utf-8") as file_handle:
            manifest = json.load(file_handle)
        archive_entries = manifest.get("archive_entries", [])
        source_entries = manifest.get("source_entries", {})
        parser_backend = str(manifest.get("parser_backend", "") or source_entries.get("parser_backend", "") or "mineru")

    bbox_json = resolve_bbox_json(raw_json_entries, source_entries, fallback_bbox_json=bbox_json)

    if logger:
        logger.log(
            "PDFParser",
            "cache_load_complete",
            data={
                "markdown_length": len(markdown),
                "image_count": len(images),
                "has_bbox": bool(bbox_json),
            },
            output_data={
                "markdown_preview": markdown[:2000] + "..." if len(markdown) > 2000 else markdown,
                "images_count": len(images),
                "bbox_keys": list(bbox_json.keys()) if bbox_json else [],
            },
            message=f"Cache load completed, markdown length: {len(markdown)}",
        )

    return PDFParseResult(
        markdown=markdown,
        images=images,
        bbox_json=bbox_json,
        raw_json_entries=raw_json_entries,
        archive_entries=archive_entries,
        source_entries=source_entries,
        parser_backend=parser_backend,
    )
