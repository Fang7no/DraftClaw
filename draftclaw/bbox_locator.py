"""
Utilities for matching issue evidence back to MinerU bbox outputs.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Sequence


REFERENCE_PATTERN = re.compile(r"\b(fig(?:ure)?|table|section|sec|eq(?:uation)?)\s*\.?\s*([0-9]+[a-z]?)", re.IGNORECASE)
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[。！？!?；;])\s+|(?<=\.)\s+(?=[A-Z0-9\"'(\[])")
ANCHOR_ID_PATTERN = re.compile(r"^P\d{3}(?:-[A-Z0-9]+)+$", re.IGNORECASE)
ANCHOR_ID_TOKEN_PATTERN = re.compile(r"P\d{3}(?:-[A-Z0-9]+)+", re.IGNORECASE)
ITEM_SENTENCE_ANCHOR_PATTERN = re.compile(r"^(P\d{3}-I\d{4})-S\d{2,}$", re.IGNORECASE)
IMAGE_MARKDOWN_LINE_PATTERN = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")
TAG_ONLY_LINE_PATTERN = re.compile(r"^</?[a-z0-9_:-]+>$", re.IGNORECASE)


def normalize_search_text(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("fig.", "figure ")
    lowered = lowered.replace("sec.", "section ")
    lowered = lowered.replace("eq.", "equation ")
    lowered = re.sub(r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff%]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    parts = [part.strip() for part in SENTENCE_BOUNDARY_PATTERN.split(text) if part.strip()]
    return parts or [text]


def clean_candidate_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    text = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", text)
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"([([{])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]}])", r"\1", text)
    return text.strip()


def make_anchor_id(
    *,
    page: int,
    bbox: Sequence[Any],
    source: str,
    item_index: int | None = None,
    sentence_index: int | None = None,
) -> str:
    page_token = f"P{max(0, int(page)):03d}"
    if item_index is not None and item_index >= 0:
        return f"{page_token}-I{int(item_index):04d}"

    source_key = re.sub(r"[^A-Z0-9]+", "", str(source or "").upper())[:8] or "BBOX"
    bbox_key = ",".join(str(int(round(float(value)))) for value in list(bbox or [])[:4])
    digest = hashlib.sha1(f"{page_token}|{source_key}|{bbox_key}".encode("utf-8")).hexdigest()[:6].upper()
    return f"{page_token}-{source_key}-{digest}"


def is_anchor_id(value: Any) -> bool:
    return bool(ANCHOR_ID_PATTERN.match(normalize_anchor_id(value)))


def normalize_anchor_id(value: Any) -> str:
    raw_text = str(value or "").strip().strip("\"'`")
    candidate = raw_text.split("|", 1)[0].strip().strip("[](){}<>").strip().upper()
    match = ANCHOR_ID_TOKEN_PATTERN.search(candidate)
    anchor_id = match.group(0).upper() if match else candidate
    match = ITEM_SENTENCE_ANCHOR_PATTERN.match(anchor_id)
    if match:
        return match.group(1)
    return anchor_id


def flatten_content_text(node: Any, *, parent_key: str = "") -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        parts = [flatten_content_text(item, parent_key=parent_key) for item in node]
        return " ".join(part for part in parts if part.strip())
    if isinstance(node, dict):
        parts: List[str] = []
        for key, value in node.items():
            if key in {"type", "bbox", "poly", "path", "image_source", "html", "latex"}:
                continue
            text = flatten_content_text(value, parent_key=key)
            if text.strip():
                parts.append(text)
        return " ".join(parts)
    return str(node)


def extract_image_paths(node: Any) -> List[str]:
    if isinstance(node, dict):
        image_source = node.get("image_source")
        if isinstance(image_source, dict):
            path = str(image_source.get("path", "")).strip()
            return [path] if path else []
    return []


def build_content_list_v2_bbox_index(content_list_v2: Any) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    pages = content_list_v2 if isinstance(content_list_v2, list) else []

    for page_index, page_items in enumerate(pages):
        if not isinstance(page_items, list):
            continue
        for item_index, item in enumerate(page_items):
            if not isinstance(item, dict):
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            text = clean_candidate_text(flatten_content_text(item.get("content", {})))
            image_paths = extract_image_paths(item.get("content", {}))
            item_type = str(item.get("type", "unknown"))
            if item_type == "image" and not text:
                text = " ".join(path for path in image_paths if path)
            items.append(
                {
                    "page": page_index + 1,
                    "item_index": item_index,
                    "type": item_type,
                    "bbox": bbox[:4],
                    "text": text,
                    "sentences": split_sentences(text),
                    "image_paths": image_paths,
                }
            )

    return {
        "source": "content_list_v2",
        "page_count": len(pages),
        "item_count": len(items),
        "items": items,
    }


def build_bbox_debug_markdown(bbox_index: Dict[str, Any]) -> str:
    items = bbox_index.get("items", []) if isinstance(bbox_index, dict) else []
    lines = [
        "# BBox Debug Markdown",
        "",
        f"- source: {bbox_index.get('source', 'unknown')}",
        f"- page_count: {bbox_index.get('page_count', 0)}",
        f"- item_count: {len(items)}",
        "",
    ]

    current_page = None
    for item in items:
        page = item.get("page")
        if page != current_page:
            current_page = page
            lines.extend([f"## Page {page}", ""])

        item_type = item.get("type", "unknown")
        item_index = item.get("item_index", 0)
        bbox = item.get("bbox", [])
        text = str(item.get("text", "")).strip()
        image_paths = item.get("image_paths", [])

        lines.append(f"### Item {item_index} | type={item_type} | bbox={bbox}")
        if image_paths:
            for image_path in image_paths:
                lines.append(f"![]({image_path})")
        if text:
            lines.append("")
            lines.append(text)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _extract_reference_keys(text: str) -> set[str]:
    return {f"{kind}:{value}" for kind, value in REFERENCE_PATTERN.findall(text)}


def _token_set(text: str) -> set[str]:
    return {token for token in normalize_search_text(text).split() if len(token) >= 2}


class BBoxLocator:
    """Search MinerU content_list_v2 outputs for evidence locations."""

    def __init__(self, bbox_json: Any, images: Sequence[Dict[str, Any]] | None = None):
        self.images = list(images or [])
        self.candidates = self._build_candidates(bbox_json, self.images)
        self.anchor_map = self._build_anchor_map(self.candidates)
        self.normalized_text_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for candidate in self.candidates:
            normalized_text = str(candidate.get("normalized_text", "")).strip()
            if normalized_text:
                self.normalized_text_map[normalized_text].append(candidate)

    @staticmethod
    def _build_anchor_map(candidates: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        anchor_map: Dict[str, Dict[str, Any]] = {}
        for candidate in sorted(candidates, key=BBoxLocator._anchor_map_priority):
            anchor_id = normalize_anchor_id(candidate.get("anchor_id", ""))
            if anchor_id and anchor_id not in anchor_map:
                anchor_map[anchor_id] = candidate
        return anchor_map

    @staticmethod
    def _anchor_map_priority(candidate: Dict[str, Any]) -> tuple[int, int, int]:
        source = str(candidate.get("source", "")).strip()
        source_rank = 1 if source == "content_list_v2_sentence" else 0
        return (
            source_rank,
            int(candidate.get("page", 0) or 0),
            int(candidate.get("item_index", 0) or 0),
        )

    def locate_issue(self, issue: Dict[str, Any], max_matches: int = 3) -> Dict[str, Any]:
        evidence_texts = self._normalize_queries(issue.get("evidence", ""))
        location_text = str(issue.get("location", "")).strip()

        evidence_anchor_ids = self._extract_anchor_ids(evidence_texts)
        location_anchor_ids = self._extract_anchor_ids([location_text])

        if evidence_anchor_ids or location_anchor_ids:
            evidence_matches = self.resolve_many(evidence_anchor_ids, max_matches=max_matches)
            location_matches = self.resolve_many(location_anchor_ids, max_matches=max_matches)
            if not evidence_matches:
                evidence_matches = self.search_many(evidence_texts, max_matches=max_matches)
            if not location_matches and location_text:
                location_matches = self.search(location_text, max_matches=max_matches)
        else:
            evidence_matches = self.search_many(evidence_texts, max_matches=max_matches)
            location_matches = self.search(location_text, max_matches=max_matches)

        best_match = location_matches[0] if location_matches else (evidence_matches[0] if evidence_matches else None)
        result = {
            "bbox_lookup_enabled": bool(self.candidates),
            "bbox_lookup_resolved": bool(best_match),
            "best_bbox_match": best_match,
            "best_bbox_match_kind": "location" if location_matches else ("evidence" if evidence_matches else ""),
            "evidence_bbox_matches": evidence_matches,
            "location_bbox_matches": location_matches,
            "evidence_anchor_ids": evidence_anchor_ids,
            "location_anchor_ids": location_anchor_ids,
        }
        if evidence_anchor_ids or location_anchor_ids:
            result.update(
                self._build_anchor_display_fields(
                    issue=issue,
                    evidence_matches=evidence_matches,
                    location_matches=location_matches,
                )
            )
        return result

    def resolve_many(self, anchor_ids: Sequence[str], max_matches: int = 3) -> List[Dict[str, Any]]:
        resolved: List[Dict[str, Any]] = []
        seen = set()
        for anchor_id in anchor_ids:
            match = self.resolve_anchor(anchor_id)
            if not match:
                continue
            key = str(match.get("anchor_id", "")).strip() or (
                int(match.get("page", 0) or 0),
                tuple(match.get("bbox", [])[:4]) if isinstance(match.get("bbox"), list) else (),
                str(match.get("source", "")).strip(),
                match.get("item_index"),
            )
            if key in seen:
                continue
            seen.add(key)
            resolved.append(match)
            if len(resolved) >= max_matches:
                break
        return resolved

    def resolve_anchor(self, anchor_id: str) -> Dict[str, Any] | None:
        candidate = self.anchor_map.get(normalize_anchor_id(anchor_id))
        if not candidate:
            return None
        return {
            "score": 1.0,
            "page": candidate["page"],
            "bbox": candidate["bbox"],
            "source": candidate["source"],
            "content_type": candidate["content_type"],
            "item_index": candidate.get("item_index"),
            "sentence_index": candidate.get("sentence_index"),
            "matched_text": candidate["text"][:240],
            "anchor_id": candidate.get("anchor_id"),
        }

    def build_anchor_catalog(
        self,
        text: str,
        *,
        max_entries: int = 80,
        preview_chars: int = 180,
    ) -> Dict[str, Any]:
        entries: List[Dict[str, Any]] = []
        seen = set()
        for segment in self._extract_catalog_segments(text):
            candidate = self._match_catalog_segment(segment)
            if not candidate:
                continue
            anchor_id = str(candidate.get("anchor_id", "")).strip()
            if not anchor_id or anchor_id in seen:
                continue
            seen.add(anchor_id)
            entry = {
                "anchor_id": anchor_id,
                "page": int(candidate.get("page", 0) or 0),
                "bbox": list(candidate.get("bbox", [])[:4]),
                "source": str(candidate.get("source", "")).strip(),
                "content_type": str(candidate.get("content_type", "")).strip(),
                "item_index": candidate.get("item_index"),
                "sentence_index": candidate.get("sentence_index"),
                "matched_text": str(candidate.get("text", "") or "")[:preview_chars],
            }
            entries.append(entry)
            if len(entries) >= max_entries:
                break

        if entries:
            catalog_text = "\n".join(
                f"- `{entry['anchor_id']}` | page={entry['page']} | bbox={entry['bbox']} | {entry['matched_text']}"
                for entry in entries
            )
        else:
            catalog_text = "(no anchor ids matched this text block)"
        return {
            "entries": entries,
            "catalog_text": catalog_text,
        }

    def build_anchored_text(
        self,
        text: str,
        *,
        max_anchors: int = 120,
    ) -> str:
        """Attach compact anchor ids directly to matched text segments."""
        source = str(text or "")
        if not source.strip():
            return source

        anchored_lines: List[str] = []
        used_count = 0
        seen_segments = set()

        for raw_line in source.splitlines():
            stripped = clean_candidate_text(raw_line)
            if not stripped or used_count >= max_anchors:
                anchored_lines.append(raw_line)
                continue
            if stripped in {"<current chunk>", "</current chunk>"}:
                anchored_lines.append(raw_line)
                continue
            if IMAGE_MARKDOWN_LINE_PATTERN.match(stripped) or TAG_ONLY_LINE_PATTERN.match(stripped):
                anchored_lines.append(raw_line)
                continue

            anchored = self._anchor_text_segment(raw_line, seen_segments=seen_segments)
            anchored_lines.append(anchored)
            if anchored != raw_line:
                used_count += 1

        return "\n".join(anchored_lines)

    @staticmethod
    def _normalize_queries(value: Any) -> List[str]:
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        normalized: List[str] = []
        seen = set()
        for item in items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    @staticmethod
    def _extract_anchor_ids(values: Sequence[str]) -> List[str]:
        anchor_ids: List[str] = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            candidate = normalize_anchor_id(text.split("|", 1)[0].strip())
            if not is_anchor_id(candidate):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            anchor_ids.append(candidate)
        return anchor_ids

    def _build_anchor_display_fields(
        self,
        *,
        issue: Dict[str, Any],
        evidence_matches: List[Dict[str, Any]],
        location_matches: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        location_match = location_matches[0] if location_matches else None
        evidence_texts = [str(match.get("matched_text", "")).strip() for match in evidence_matches if str(match.get("matched_text", "")).strip()]
        location_text = str(location_match.get("matched_text", "")).strip() if location_match else ""

        location_anchor = normalize_anchor_id(issue.get("location", ""))
        evidence_anchors = [
            normalize_anchor_id(item)
            for item in self._normalize_queries(issue.get("evidence", []))
            if is_anchor_id(item)
        ]

        location_display = location_anchor
        if location_anchor and location_text:
            location_display = f"{location_anchor} | {location_text}"

        evidence_display_parts = []
        for index, anchor in enumerate(evidence_anchors):
            text = evidence_texts[index] if index < len(evidence_texts) else ""
            evidence_display_parts.append(f"{anchor} | {text}" if text else anchor)

        return {
            "location_original": location_text,
            "evidence_original": evidence_texts,
            "location_display": location_display or location_text,
            "evidence_display": "\n".join(part for part in evidence_display_parts if part),
        }

    def _match_catalog_segment(self, text: str) -> Dict[str, Any] | None:
        normalized = normalize_search_text(clean_candidate_text(text))
        if not normalized:
            return None

        exact_candidates = self.normalized_text_map.get(normalized, [])
        if exact_candidates:
            return sorted(exact_candidates, key=self._candidate_priority)[0]

        fuzzy_matches = self.search(text, max_matches=1)
        if fuzzy_matches and float(fuzzy_matches[0].get("score", 0.0) or 0.0) >= 0.95:
            return self.anchor_map.get(normalize_anchor_id(fuzzy_matches[0].get("anchor_id", "")))
        return None

    def _anchor_text_segment(self, text: str, *, seen_segments: set[str]) -> str:
        stripped = clean_candidate_text(text)
        if not stripped:
            return str(text or "")
        normalized = normalize_search_text(stripped)
        if normalized in seen_segments:
            return str(text or "")

        candidate = self._match_catalog_segment(stripped)
        anchor_id = str(candidate.get("anchor_id", "")).strip() if candidate else ""
        if not anchor_id:
            return str(text or "")

        seen_segments.add(normalized)
        leading = re.match(r"^\s*", str(text or "")).group(0)
        return f"{leading}[{anchor_id}] {stripped}"

    @staticmethod
    def _candidate_priority(candidate: Dict[str, Any]) -> tuple[int, int, int, int]:
        source = str(candidate.get("source", "")).strip()
        source_rank = 0 if source == "content_list_v2_sentence" else 1
        return (
            source_rank,
            int(candidate.get("page", 0) or 0),
            int(candidate.get("item_index", 0) or 0),
            int(candidate.get("sentence_index", 0) or 0),
        )

    @staticmethod
    def _extract_catalog_segments(text: str) -> List[str]:
        segments: List[str] = []
        seen = set()
        for raw_line in str(text or "").splitlines():
            stripped = clean_candidate_text(raw_line)
            if not stripped:
                continue
            if stripped in {"<current chunk>", "</current chunk>"}:
                continue
            if IMAGE_MARKDOWN_LINE_PATTERN.match(stripped):
                continue
            if TAG_ONLY_LINE_PATTERN.match(stripped):
                continue

            lowered = stripped.lower()
            if stripped.startswith("#") or lowered.startswith("figure ") or lowered.startswith("table ") or "<table" in lowered:
                if stripped not in seen:
                    seen.add(stripped)
                    segments.append(stripped)
                continue

            if stripped not in seen:
                seen.add(stripped)
                segments.append(stripped)
        return segments

    def search_many(self, queries: Sequence[str], max_matches: int = 3) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for query in queries:
            for match in self.search(query, max_matches=max_matches):
                key = str(match.get("anchor_id", "")).strip() or (
                    int(match.get("page", 0) or 0),
                    tuple(match.get("bbox", [])[:4]) if isinstance(match.get("bbox"), list) else (),
                    str(match.get("source", "")).strip(),
                    match.get("item_index"),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(match)
        merged.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return merged[:max_matches]

    def search(self, query: str, max_matches: int = 3) -> List[Dict[str, Any]]:
        query = str(query or "").strip()
        query_normalized = normalize_search_text(query)
        if not query_normalized:
            return []

        scored_candidates = []
        for candidate in self.candidates:
            score = self._score_candidate(query, query_normalized, candidate)
            if score < 0.35:
                continue
            scored_candidates.append((score, candidate))

        scored_candidates.sort(key=lambda item: item[0], reverse=True)

        results: List[Dict[str, Any]] = []
        seen = set()
        for score, candidate in scored_candidates:
            key = str(candidate.get("anchor_id", "")).strip() or (
                candidate["page"],
                tuple(candidate["bbox"]),
                candidate["source"],
                candidate.get("item_index"),
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "score": round(score, 3),
                    "page": candidate["page"],
                    "bbox": candidate["bbox"],
                    "source": candidate["source"],
                    "content_type": candidate["content_type"],
                    "item_index": candidate.get("item_index"),
                    "sentence_index": candidate.get("sentence_index"),
                    "matched_text": candidate["text"][:240],
                    "anchor_id": candidate.get("anchor_id"),
                }
            )
            if len(results) >= max_matches:
                break

        return results

    def _score_candidate(self, query: str, query_normalized: str, candidate: Dict[str, Any]) -> float:
        candidate_text = candidate["normalized_text"]
        if not candidate_text:
            return 0.0

        if query_normalized == candidate_text:
            return 1.0

        score = 0.0

        if len(query_normalized) >= 12 and query_normalized in candidate_text:
            coverage = len(query_normalized) / max(len(candidate_text), 1)
            score = max(score, 0.78 + min(coverage, 1.0) * 0.18)

        if len(candidate_text) >= 12 and candidate_text in query_normalized:
            coverage = len(candidate_text) / max(len(query_normalized), 1)
            score = max(score, 0.68 + min(coverage, 1.0) * 0.15)

        query_tokens = _token_set(query)
        candidate_tokens = candidate["tokens"]
        if query_tokens and candidate_tokens:
            token_overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
            score = max(score, token_overlap * 0.82)

        sequence_score = SequenceMatcher(None, query_normalized, candidate_text).ratio()
        score = max(score, sequence_score * 0.72)

        query_refs = _extract_reference_keys(query_normalized)
        candidate_refs = candidate["references"]
        if query_refs and candidate_refs and query_refs & candidate_refs:
            score += 0.2

        return min(score, 1.0)

    @staticmethod
    def _build_candidates(bbox_json: Any, images: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        bbox_index = BBoxLocator._normalize_bbox_source(bbox_json)
        if bbox_index:
            return BBoxLocator._build_content_list_v2_candidates(bbox_index)
        return BBoxLocator._build_legacy_candidates(bbox_json or {}, images)

    @staticmethod
    def _normalize_bbox_source(bbox_json: Any) -> Dict[str, Any]:
        if isinstance(bbox_json, dict) and bbox_json.get("source") == "content_list_v2":
            return bbox_json
        if isinstance(bbox_json, dict) and isinstance(bbox_json.get("content_list_v2"), list):
            return build_content_list_v2_bbox_index(bbox_json["content_list_v2"])
        if isinstance(bbox_json, list):
            return build_content_list_v2_bbox_index(bbox_json)
        return {}

    @staticmethod
    def _build_content_list_v2_candidates(bbox_index: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for item in bbox_index.get("items", []) or []:
            text = str(item.get("text", "")).strip()
            bbox = item.get("bbox")
            if not text or not isinstance(bbox, list) or len(bbox) < 4:
                continue

            candidates.append(
                BBoxLocator._make_candidate(
                    text=text,
                    bbox=bbox[:4],
                    page=int(item.get("page", 0)),
                    source="content_list_v2_item",
                    content_type=str(item.get("type", "text")),
                    item_index=int(item.get("item_index", 0)),
                )
            )

            for sentence_index, sentence in enumerate(item.get("sentences", [])):
                sentence = str(sentence).strip()
                if not sentence or sentence == text:
                    continue
                candidates.append(
                    BBoxLocator._make_candidate(
                        text=sentence,
                        bbox=bbox[:4],
                        page=int(item.get("page", 0)),
                        source="content_list_v2_sentence",
                        content_type=str(item.get("type", "text")),
                        item_index=int(item.get("item_index", 0)),
                        sentence_index=sentence_index,
                    )
                )

        return candidates

    @staticmethod
    def _build_legacy_candidates(bbox_json: Dict[str, Any], images: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        pdf_info = bbox_json.get("pdf_info", []) if isinstance(bbox_json, dict) else []
        if isinstance(pdf_info, list):
            for page_index, page in enumerate(pdf_info):
                for block in page.get("para_blocks", []) or []:
                    candidates.extend(BBoxLocator._extract_block_candidates(page_index, block))

        for image in images:
            bbox = image.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue

            caption_parts = []
            caption_parts.extend(str(item) for item in image.get("image_caption", []) if str(item).strip())
            caption_parts.extend(str(item) for item in image.get("image_footnote", []) if str(item).strip())
            caption_parts.append(str(image.get("img_path", "")))
            text = " ".join(part.strip() for part in caption_parts if part.strip())
            if not text:
                continue

            candidates.append(
                BBoxLocator._make_candidate(
                    text=text,
                    bbox=bbox,
                    page=int(image.get("page_idx", 0)) + 1,
                    source="mineru_image",
                    content_type="image_caption",
                )
            )

        return candidates

    @staticmethod
    def _extract_block_candidates(page_index: int, block: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        block_text_parts: List[str] = []

        for line in block.get("lines", []) or []:
            line_text_parts: List[str] = []
            for span in line.get("spans", []) or []:
                span_text = str(span.get("content", "")).strip()
                if span_text:
                    line_text_parts.append(span_text)

            line_text = " ".join(line_text_parts).strip()
            if line_text and isinstance(line.get("bbox"), list) and len(line["bbox"]) == 4:
                candidates.append(
                    BBoxLocator._make_candidate(
                        text=line_text,
                        bbox=line["bbox"],
                        page=page_index + 1,
                        source="layout_line",
                        content_type=str(block.get("type", "text")),
                    )
                )
                block_text_parts.append(line_text)

        block_text = " ".join(block_text_parts).strip()
        block_bbox = block.get("bbox")
        if block_text and isinstance(block_bbox, list) and len(block_bbox) == 4:
            candidates.append(
                BBoxLocator._make_candidate(
                    text=block_text,
                    bbox=block_bbox,
                    page=page_index + 1,
                    source="layout_block",
                    content_type=str(block.get("type", "text")),
                )
            )

        return candidates

    @staticmethod
    def _make_candidate(
        *,
        text: str,
        bbox: List[Any],
        page: int,
        source: str,
        content_type: str,
        item_index: int | None = None,
        sentence_index: int | None = None,
    ) -> Dict[str, Any]:
        normalized_text = normalize_search_text(text)
        anchor_id = make_anchor_id(
            page=page,
            bbox=bbox,
            source=source,
            item_index=item_index,
            sentence_index=sentence_index,
        )
        return {
            "text": text,
            "normalized_text": normalized_text,
            "tokens": _token_set(text),
            "references": _extract_reference_keys(normalized_text),
            "bbox": bbox,
            "page": page,
            "source": source,
            "content_type": content_type,
            "item_index": item_index,
            "sentence_index": sentence_index,
            "anchor_id": anchor_id,
        }
