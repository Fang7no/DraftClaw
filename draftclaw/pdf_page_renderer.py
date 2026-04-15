"""
Render full PDF pages as images for the web UI and exported reports.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import fitz


DEFAULT_PAGE_RENDER_SCALE = 1.35


def _normalized_scale(scale: float) -> float:
    return round(max(0.5, min(float(scale or DEFAULT_PAGE_RENDER_SCALE), 3.0)), 2)


@lru_cache(maxsize=32)
def _page_manifest(pdf_path: str, scale: float) -> tuple[dict, ...]:
    pdf_path = str(Path(pdf_path))
    render_scale = _normalized_scale(scale)
    document = fitz.open(pdf_path)
    try:
        pages: List[Dict[str, float]] = []
        for index in range(document.page_count):
            page = document[index]
            pages.append(
                {
                    "page_number": index + 1,
                    "width": round(float(page.rect.width) * render_scale, 2),
                    "height": round(float(page.rect.height) * render_scale, 2),
                }
            )
        return tuple(pages)
    finally:
        document.close()


@lru_cache(maxsize=256)
def _page_png_bytes(pdf_path: str, page_number: int, scale: float) -> bytes:
    pdf_path = str(Path(pdf_path))
    render_scale = _normalized_scale(scale)
    document = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > document.page_count:
            raise IndexError(f"Page {page_number} out of range")
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def build_page_manifest(pdf_path: str, *, scale: float = DEFAULT_PAGE_RENDER_SCALE) -> Dict[str, object]:
    pages = [dict(item) for item in _page_manifest(str(Path(pdf_path)), _normalized_scale(scale))]
    return {
        "page_count": len(pages),
        "render_scale": _normalized_scale(scale),
        "pages": pages,
    }


def render_page_png(pdf_path: str, page_number: int, *, scale: float = DEFAULT_PAGE_RENDER_SCALE) -> bytes:
    return _page_png_bytes(str(Path(pdf_path)), int(page_number), _normalized_scale(scale))


def build_embedded_page_manifest(pdf_path: str, *, scale: float = DEFAULT_PAGE_RENDER_SCALE) -> Dict[str, object]:
    manifest = build_page_manifest(pdf_path, scale=scale)
    pages_with_data: List[Dict[str, object]] = []
    for page in manifest["pages"]:
        page_number = int(page["page_number"])
        image_bytes = render_page_png(pdf_path, page_number, scale=scale)
        pages_with_data.append(
            {
                **page,
                "image_data_url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}",
            }
        )
    return {
        **manifest,
        "pages": pages_with_data,
    }
