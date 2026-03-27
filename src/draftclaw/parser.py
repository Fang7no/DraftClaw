from __future__ import annotations

from pathlib import Path
from typing import Any

from draftclaw._core.contracts import DocumentText
from draftclaw._io.docling_parser import DoclingDocumentParser


class DraftClawDocumentParser:
    """Public facade for DraftClaw document parsing."""

    def __init__(
        self,
        *,
        text_fast_path: bool = True,
        cache_in_process: bool = True,
        cache_on_disk: bool = True,
        docling_page_chunk_size: int | None = 8,
        pdf_parse_mode: str = "fast",
        paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
        paddleocr_api_key: str = "",
        paddleocr_api_model: str = "PaddleOCR-VL-1.5",
        paddleocr_poll_interval_sec: float = 5.0,
        paddleocr_api_timeout_sec: float = 120.0,
        working_dir: str | Path | None = None,
    ) -> None:
        self._parser = DoclingDocumentParser(
            text_fast_path=text_fast_path,
            cache_in_process=cache_in_process,
            cache_on_disk=cache_on_disk,
            docling_page_chunk_size=docling_page_chunk_size,
            pdf_parse_mode=pdf_parse_mode,
            paddleocr_api_url=paddleocr_api_url,
            paddleocr_api_key=paddleocr_api_key,
            paddleocr_api_model=paddleocr_api_model,
            paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
            paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
            working_dir=working_dir,
        )

    def parse(self, input_path: str | Path) -> DocumentText:
        return self._parser.parse(input_path)

    def parse_text(self, input_path: str | Path) -> str:
        return self.parse(input_path).text

    def capability_report(self) -> dict[str, dict[str, str | bool]]:
        return self._parser.capability_report()


def create_document_parser(
    *,
    text_fast_path: bool = True,
    cache_in_process: bool = True,
    cache_on_disk: bool = True,
    docling_page_chunk_size: int | None = 8,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
    paddleocr_poll_interval_sec: float = 5.0,
    paddleocr_api_timeout_sec: float = 120.0,
    working_dir: str | Path | None = None,
) -> DraftClawDocumentParser:
    return DraftClawDocumentParser(
        text_fast_path=text_fast_path,
        cache_in_process=cache_in_process,
        cache_on_disk=cache_on_disk,
        docling_page_chunk_size=docling_page_chunk_size,
        pdf_parse_mode=pdf_parse_mode,
        paddleocr_api_url=paddleocr_api_url,
        paddleocr_api_key=paddleocr_api_key,
        paddleocr_api_model=paddleocr_api_model,
        paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
        paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
        working_dir=working_dir,
    )


def parse_document(
    input_path: str | Path,
    *,
    text_fast_path: bool = True,
    cache_in_process: bool = True,
    cache_on_disk: bool = True,
    docling_page_chunk_size: int | None = 8,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
    paddleocr_poll_interval_sec: float = 5.0,
    paddleocr_api_timeout_sec: float = 120.0,
    working_dir: str | Path | None = None,
) -> DocumentText:
    parser = create_document_parser(
        text_fast_path=text_fast_path,
        cache_in_process=cache_in_process,
        cache_on_disk=cache_on_disk,
        docling_page_chunk_size=docling_page_chunk_size,
        pdf_parse_mode=pdf_parse_mode,
        paddleocr_api_url=paddleocr_api_url,
        paddleocr_api_key=paddleocr_api_key,
        paddleocr_api_model=paddleocr_api_model,
        paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
        paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
        working_dir=working_dir,
    )
    return parser.parse(input_path)


def parse_document_text(
    input_path: str | Path,
    *,
    text_fast_path: bool = True,
    cache_in_process: bool = True,
    cache_on_disk: bool = True,
    docling_page_chunk_size: int | None = 8,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
    paddleocr_poll_interval_sec: float = 5.0,
    paddleocr_api_timeout_sec: float = 120.0,
    working_dir: str | Path | None = None,
) -> str:
    return parse_document(
        input_path,
        text_fast_path=text_fast_path,
        cache_in_process=cache_in_process,
        cache_on_disk=cache_on_disk,
        docling_page_chunk_size=docling_page_chunk_size,
        pdf_parse_mode=pdf_parse_mode,
        paddleocr_api_url=paddleocr_api_url,
        paddleocr_api_key=paddleocr_api_key,
        paddleocr_api_model=paddleocr_api_model,
        paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
        paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
        working_dir=working_dir,
    ).text


def parse_document_file(
    input_path: str | Path,
    *,
    text_fast_path: bool = True,
    cache_in_process: bool = True,
    cache_on_disk: bool = True,
    docling_page_chunk_size: int | None = 8,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
    paddleocr_poll_interval_sec: float = 5.0,
    paddleocr_api_timeout_sec: float = 120.0,
    working_dir: str | Path | None = None,
) -> dict[str, Any]:
    return parse_document(
        input_path,
        text_fast_path=text_fast_path,
        cache_in_process=cache_in_process,
        cache_on_disk=cache_on_disk,
        docling_page_chunk_size=docling_page_chunk_size,
        pdf_parse_mode=pdf_parse_mode,
        paddleocr_api_url=paddleocr_api_url,
        paddleocr_api_key=paddleocr_api_key,
        paddleocr_api_model=paddleocr_api_model,
        paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
        paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
        working_dir=working_dir,
    ).model_dump(mode="json")


__all__ = [
    "DraftClawDocumentParser",
    "create_document_parser",
    "parse_document",
    "parse_document_file",
    "parse_document_text",
]
