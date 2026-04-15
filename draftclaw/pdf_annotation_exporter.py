"""
Export DraftClaw issues as PDF annotations.
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any, Dict, Iterable, Optional

import fitz

from config import BBOX_EXPAND_X_PT, BBOX_EXPAND_Y_PT, BBOX_NORMALIZED_SIZE
from issue_review import issue_is_dropped


def _pick_location_match(issue: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    location_matches = issue.get("location_bbox_matches")
    if isinstance(location_matches, list):
        valid = [item for item in location_matches if isinstance(item, dict) and isinstance(item.get("bbox"), list)]
        valid.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        if valid:
            return valid[0]

    best_match = issue.get("best_bbox_match")
    if isinstance(best_match, dict) and isinstance(best_match.get("bbox"), list):
        return best_match
    return None


def _to_page_rect(page: fitz.Page, bbox: Iterable[Any]) -> fitz.Rect:
    x0, y0, x1, y1 = list(bbox)[:4]
    width = float(page.rect.width or 1.0)
    height = float(page.rect.height or 1.0)
    normalized_size = float(BBOX_NORMALIZED_SIZE or 1000)
    rect = fitz.Rect(
        max(0.0, min(width, float(x0) * width / normalized_size)),
        max(0.0, min(height, float(y0) * height / normalized_size)),
        max(0.0, min(width, float(x1) * width / normalized_size)),
        max(0.0, min(height, float(y1) * height / normalized_size)),
    )
    expanded = fitz.Rect(
        max(page.rect.x0, rect.x0 - float(BBOX_EXPAND_X_PT)),
        max(page.rect.y0, rect.y0 - float(BBOX_EXPAND_Y_PT)),
        min(page.rect.x1, rect.x1 + float(BBOX_EXPAND_X_PT)),
        min(page.rect.y1, rect.y1 + float(BBOX_EXPAND_Y_PT)),
    )
    return expanded


def _issue_note(issue: Dict[str, Any]) -> str:
    issue_type = str(issue.get("type", "") or "").strip() or "N/A"
    description = str(issue.get("description", "") or "").strip() or "N/A"
    reasoning = str(issue.get("reasoning", "") or "").strip() or "N/A"
    return (
        f"Issues Type: {issue_type}\n"
        f"Description: {description}\n"
        f"Reasoning: {reasoning}"
    )


def _annotation_icon_point(page: fitz.Page, rect: fitz.Rect) -> fitz.Point:
    icon_margin = 14.0
    icon_x = min(page.rect.x1 - icon_margin, rect.x1 + 10.0)
    if icon_x < page.rect.x0 + icon_margin:
        icon_x = page.rect.x0 + icon_margin
    if icon_x > page.rect.x1 - icon_margin:
        icon_x = max(page.rect.x0 + icon_margin, rect.x0)

    icon_y = min(page.rect.y1 - icon_margin, max(page.rect.y0 + icon_margin, rect.y0))
    return fitz.Point(icon_x, icon_y)


def _popup_rect(page: fitz.Page, rect: fitz.Rect, icon_point: fitz.Point, note_text: str) -> fitz.Rect:
    page_margin = 16.0
    page_width = float(page.rect.width or 1.0)
    page_height = float(page.rect.height or 1.0)
    usable_width = max(120.0, page_width - page_margin * 2.0)
    usable_height = max(120.0, page_height - page_margin * 2.0)

    longest_line = max((len(line) for line in note_text.splitlines()), default=0)
    wrapped_lines = sum(
        max(1, math.ceil(max(len(line), 1) / 66.0))
        for line in note_text.splitlines()
    ) or 1

    popup_width = min(usable_width, max(260.0, min(420.0, 180.0 + longest_line * 3.2)))
    popup_height = min(usable_height, max(190.0, min(420.0, 92.0 + wrapped_lines * 22.0)))

    popup_x0 = icon_point.x + 22.0
    if popup_x0 + popup_width > page.rect.x1 - page_margin:
        popup_x0 = max(page.rect.x0 + page_margin, icon_point.x - popup_width - 22.0)

    popup_y0 = min(max(page.rect.y0 + page_margin, rect.y0 - 8.0), page.rect.y1 - popup_height - page_margin)
    return fitz.Rect(
        popup_x0,
        popup_y0,
        popup_x0 + popup_width,
        popup_y0 + popup_height,
    )


def export_annotated_pdf_bytes(report_data: Dict[str, Any], pdf_path: str) -> bytes:
    document = fitz.open(pdf_path)
    try:
        for issue in report_data.get("issues", []):
            if not isinstance(issue, dict) or issue_is_dropped(issue):
                continue

            target_match = _pick_location_match(issue)
            if not target_match:
                continue

            page_number = int(target_match.get("page", 0) or 0)
            bbox = target_match.get("bbox", [])
            if page_number <= 0 or not isinstance(bbox, list) or len(bbox) < 4:
                continue

            page = document[page_number - 1]
            rect = _to_page_rect(page, bbox)
            if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                continue

            note_text = _issue_note(issue)
            note_point = _annotation_icon_point(page, rect)
            popup_rect = _popup_rect(page, rect, note_point, note_text)

            rect_annot = page.add_rect_annot(rect)
            rect_annot.set_colors(stroke=(1.0, 0.2, 0.2))
            rect_annot.set_border(width=1.3)
            rect_annot.set_opacity(0.9)
            rect_annot.set_info(title="DraftClaw", subject="DraftClaw Issue", content=note_text)
            rect_annot.set_popup(popup_rect)
            rect_annot.set_open(False)
            rect_annot.update()

            text_annot = page.add_text_annot(note_point, note_text)
            text_annot.set_name("Comment")
            text_annot.set_info(title="DraftClaw", subject="DraftClaw Issue", content=note_text)
            text_annot.set_popup(popup_rect)
            text_annot.set_open(False)
            text_annot.update()

        buffer = BytesIO()
        document.save(
            buffer,
            garbage=4,
            deflate=True,
            incremental=False,
        )
        return buffer.getvalue()
    finally:
        document.close()
