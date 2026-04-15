"""
Render bbox-centered PDF crops for vision validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import fitz
from PIL import Image, ImageDraw, ImageOps

from config import BBOX_OUTLINE_WIDTH

try:  # pragma: no cover - optional dependency
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

try:  # pragma: no cover - optional dependency
    from paddleocr import PaddleOCR
except ImportError:  # pragma: no cover - optional dependency
    PaddleOCR = None

try:  # pragma: no cover - optional dependency
    import pytesseract
except ImportError:  # pragma: no cover - optional dependency
    pytesseract = None


_PADDLE_OCR_ENGINE = None
_PADDLE_OCR_ENGINE_INITIALIZED = False


def _is_unknown_paddle_argument_error(exc: Exception, argument_name: str) -> bool:
    message = str(exc or "").strip().lower()
    argument_name = str(argument_name or "").strip().lower()
    if not message or not argument_name:
        return False
    return (
        f"unknown argument: {argument_name}" in message
        or ("unexpected keyword argument" in message and argument_name in message)
    )


def _create_paddle_ocr_engine() -> Any:
    init_variants = (
        {"use_angle_cls": False, "lang": "en", "show_log": False},
        {"use_angle_cls": False, "lang": "en"},
        {"lang": "en"},
    )
    last_error: Exception | None = None
    for kwargs in init_variants:
        try:
            return PaddleOCR(**kwargs)
        except Exception as exc:  # pragma: no cover - depends on installed PaddleOCR version
            last_error = exc
            if _is_unknown_paddle_argument_error(exc, "show_log"):
                continue
            if _is_unknown_paddle_argument_error(exc, "use_angle_cls"):
                continue
            break
    if last_error is not None:
        raise last_error
    return None


def _get_paddle_ocr_engine() -> Any:
    global _PADDLE_OCR_ENGINE
    global _PADDLE_OCR_ENGINE_INITIALIZED
    if PaddleOCR is None:
        return None
    if _PADDLE_OCR_ENGINE_INITIALIZED:
        return _PADDLE_OCR_ENGINE
    _PADDLE_OCR_ENGINE_INITIALIZED = True
    try:
        _PADDLE_OCR_ENGINE = _create_paddle_ocr_engine()
    except Exception:
        # OCR is optional for bbox screenshots. If PaddleOCR cannot be initialized
        # in the current runtime, fall back to tesseract or PDF text extraction.
        _PADDLE_OCR_ENGINE = None
    return _PADDLE_OCR_ENGINE


class PDFIssueScreenshotRenderer:
    """Render tightly cropped bbox screenshots and attach OCR text."""

    def __init__(
        self,
        pdf_path: str,
        output_dir: Path,
        *,
        page_zoom: float = 1.5,
        crop_zoom: float = 2.2,
        bbox_padding: float = 24.0,
        max_matches: int | None = 2,
        bbox_normalized_size: int = 1000,
        bbox_outline_width: int = BBOX_OUTLINE_WIDTH,
        bbox_expand_x_pt: float = 0.0,
        bbox_expand_y_pt: float = 0.0,
    ) -> None:
        self.pdf_path = str(pdf_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.page_zoom = max(1.0, float(page_zoom))
        self.crop_zoom = max(1.0, float(crop_zoom))
        self.bbox_padding = max(0.0, float(bbox_padding))
        self.max_matches = None if max_matches is None else max(1, int(max_matches))
        self.bbox_normalized_size = max(1, int(bbox_normalized_size))
        self.bbox_outline_width = max(1, int(round(float(bbox_outline_width))))
        self.bbox_expand_x_pt = max(0.0, float(bbox_expand_x_pt))
        self.bbox_expand_y_pt = max(0.0, float(bbox_expand_y_pt))
        self.document = fitz.open(self.pdf_path)

    def close(self) -> None:
        self.document.close()

    def render_issue(
        self,
        issue: Dict[str, Any],
        issue_index: int,
        *,
        max_matches: int | None = None,
    ) -> List[Dict[str, Any]]:
        screenshots: List[Dict[str, Any]] = []
        effective_max_matches = self.max_matches if max_matches is None else max_matches
        for match_kind, match in self._collect_matches(issue, max_matches=effective_max_matches):
            page_number = int(match.get("page", 0) or 0)
            raw_bbox = match.get("bbox", [])
            if page_number <= 0 or not isinstance(raw_bbox, list) or len(raw_bbox) < 4:
                continue

            page_bbox = self._to_page_bbox(page_number, raw_bbox[:4])
            clip_bbox = self._clip_bbox(page_number, page_bbox)
            crop_image = self._render_crop(page_number, page_bbox, clip_bbox)
            ocr_text, ocr_source = self._extract_crop_text(page_number, clip_bbox, crop_image)

            image_path = self.output_dir / (
                f"issue{issue_index:04d}_{match_kind}_page{page_number:03d}.png"
            )
            crop_image.save(image_path)

            screenshots.append(
                {
                    "kind": match_kind,
                    "page": page_number,
                    "bbox": raw_bbox[:4],
                    "page_bbox": page_bbox,
                    "clip_bbox": clip_bbox,
                    "bbox_coordinate_system": f"normalized_{self.bbox_normalized_size}",
                    "bbox_outline_width": self.bbox_outline_width,
                    "bbox_expand_x_pt": 0.0,
                    "bbox_expand_y_pt": 0.0,
                    "matched_text": str(match.get("matched_text", "") or ""),
                    "ocr_text": ocr_text,
                    "ocr_source": ocr_source,
                    "local_path": str(image_path),
                    "page_idx": page_number - 1,
                    "image_caption": [
                        (
                            f"{match_kind} bbox crop | page {page_number} | "
                            f"normalized_bbox {raw_bbox[:4]} | page_bbox {page_bbox} | "
                            f"clip_bbox {clip_bbox} | coord normalized_{self.bbox_normalized_size} | "
                            f"matched text: {str(match.get('matched_text', '') or '')[:220]} | "
                            f"ocr({ocr_source}): {ocr_text[:220]}"
                        )
                    ],
                }
            )

        return screenshots

    def _collect_matches(
        self,
        issue: Dict[str, Any],
        *,
        max_matches: int | None,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        collected: List[Tuple[str, Dict[str, Any]]] = []
        seen = set()
        for match_kind in ("evidence_bbox_matches", "location_bbox_matches"):
            matches = issue.get(match_kind, [])
            label = "evidence" if match_kind.startswith("evidence") else "location"
            if not isinstance(matches, list):
                continue
            for match in matches:
                if not isinstance(match, dict):
                    continue
                key = (
                    int(match.get("page", 0) or 0),
                    tuple(match.get("bbox", [])[:4]) if isinstance(match.get("bbox"), list) else (),
                )
                if key in seen:
                    continue
                seen.add(key)
                collected.append((label, match))
                if max_matches is not None and len(collected) >= max_matches:
                    return collected

        best_match = issue.get("best_bbox_match")
        if isinstance(best_match, dict):
            key = (
                int(best_match.get("page", 0) or 0),
                tuple(best_match.get("bbox", [])[:4]) if isinstance(best_match.get("bbox"), list) else (),
            )
            if key not in seen:
                collected.append(("best", best_match))
        return collected if max_matches is None else collected[: max_matches]

    def _to_page_bbox(self, page_number: int, bbox: List[Any]) -> List[float]:
        page = self.document[page_number - 1]
        width = float(page.rect.width or 1.0)
        height = float(page.rect.height or 1.0)
        normalized_size = float(self.bbox_normalized_size)
        x0 = max(0.0, min(width, float(bbox[0]) * width / normalized_size))
        y0 = max(0.0, min(height, float(bbox[1]) * height / normalized_size))
        x1 = max(0.0, min(width, float(bbox[2]) * width / normalized_size))
        y1 = max(0.0, min(height, float(bbox[3]) * height / normalized_size))
        return self._sanitize_bbox(page.rect, [x0, y0, x1, y1])

    def _clip_bbox(self, page_number: int, bbox: List[float]) -> List[float]:
        page = self.document[page_number - 1]
        page_rect = page.rect
        padding = 0.0
        clip_bbox = [
            max(float(page_rect.x0), float(bbox[0]) - padding),
            max(float(page_rect.y0), float(bbox[1]) - padding),
            min(float(page_rect.x1), float(bbox[2]) + padding),
            min(float(page_rect.y1), float(bbox[3]) + padding),
        ]
        return self._sanitize_bbox(page_rect, clip_bbox)

    @staticmethod
    def _sanitize_bbox(page_rect: fitz.Rect, bbox: List[float]) -> List[float]:
        x0, y0, x1, y1 = (float(value) for value in bbox[:4])
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        min_size = 1.0
        if (x1 - x0) < min_size:
            center_x = (x0 + x1) / 2.0
            x0 = center_x - min_size / 2.0
            x1 = center_x + min_size / 2.0
        if (y1 - y0) < min_size:
            center_y = (y0 + y1) / 2.0
            y0 = center_y - min_size / 2.0
            y1 = center_y + min_size / 2.0
        x0 = max(float(page_rect.x0), x0)
        y0 = max(float(page_rect.y0), y0)
        x1 = min(float(page_rect.x1), x1)
        y1 = min(float(page_rect.y1), y1)
        return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]

    def _render_crop(self, page_number: int, bbox: List[Any], clip_bbox: List[Any]) -> Image.Image:
        page = self.document[page_number - 1]
        clip = fitz.Rect(*clip_bbox)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(self.crop_zoom, self.crop_zoom), clip=clip, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        draw = ImageDraw.Draw(image)
        rect = [
            int(round((float(bbox[0]) - clip.x0) * self.crop_zoom)),
            int(round((float(bbox[1]) - clip.y0) * self.crop_zoom)),
            int(round((float(bbox[2]) - clip.x0) * self.crop_zoom)),
            int(round((float(bbox[3]) - clip.y0) * self.crop_zoom)),
        ]
        inset = max(0, self.bbox_outline_width // 2)
        max_x = max(0, image.width - 1)
        max_y = max(0, image.height - 1)
        rect = [
            max(0, min(max_x - inset, rect[0])),
            max(0, min(max_y - inset, rect[1])),
            max(inset, min(max_x, rect[2] - inset)),
            max(inset, min(max_y, rect[3] - inset)),
        ]
        draw.rectangle(rect, outline=(220, 46, 46), width=self.bbox_outline_width)
        return image

    def _extract_crop_text(
        self,
        page_number: int,
        clip_bbox: List[float],
        crop_image: Image.Image,
    ) -> Tuple[str, str]:
        ocr_text = self._extract_with_paddleocr(crop_image)
        if ocr_text:
            return ocr_text, "paddleocr"

        ocr_text = self._extract_with_tesseract(crop_image)
        if ocr_text:
            return ocr_text, "tesseract"

        page = self.document[page_number - 1]
        clip = fitz.Rect(*clip_bbox)
        fallback_text = " ".join(page.get_text("text", clip=clip).split())
        if fallback_text:
            return fallback_text, "pdf_clip_text"

        return "", "none"

    @staticmethod
    def _extract_with_paddleocr(crop_image: Image.Image) -> str:
        if PaddleOCR is None or np is None:
            return ""
        engine = _get_paddle_ocr_engine()
        if engine is None:
            return ""
        try:
            rgb_image = crop_image.convert("RGB")
            if rgb_image.width < 120 or rgb_image.height < 40:
                rgb_image = rgb_image.resize(
                    (max(120, rgb_image.width * 2), max(40, rgb_image.height * 2)),
                    Image.Resampling.LANCZOS,
                )
            result = engine.ocr(np.asarray(rgb_image), cls=False)
        except Exception:
            return ""

        lines: List[str] = []
        for block in result or []:
            for item in block or []:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text_info = item[1]
                if not isinstance(text_info, (list, tuple)) or not text_info:
                    continue
                text = str(text_info[0] or "").strip()
                if text:
                    lines.append(text)
        return " ".join(lines)

    @staticmethod
    def _extract_with_tesseract(crop_image: Image.Image) -> str:
        if pytesseract is None:
            return ""
        try:
            grayscale = ImageOps.grayscale(crop_image)
            enhanced = ImageOps.autocontrast(grayscale)
            if enhanced.width < 120 or enhanced.height < 40:
                enhanced = enhanced.resize(
                    (max(120, enhanced.width * 2), max(40, enhanced.height * 2)),
                    Image.Resampling.LANCZOS,
                )
            text = pytesseract.image_to_string(enhanced, config="--psm 6")
        except Exception:
            return ""
        return " ".join(str(text or "").split())
