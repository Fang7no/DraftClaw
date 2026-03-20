from __future__ import annotations

import hashlib
import json
import re
from os import stat_result
from pathlib import Path
from typing import Any

from draftclaw._core.contracts import DocumentText
from draftclaw._core.enums import InputType
from draftclaw._core.exceptions import InputLoadError


class DoclingDocumentParser:
    _DISK_CACHE_VERSION = 3
    _TEXT_FAST_PATH_SUFFIXES = {".txt", ".md"}
    _DOCLING_SUFFIXES = {".pdf", ".docx", ".pptx", ".html", ".htm", ".adoc", ".asciidoc"}
    _SUPPORTED_SUFFIXES = _TEXT_FAST_PATH_SUFFIXES | _DOCLING_SUFFIXES

    def __init__(
        self,
        *,
        text_fast_path: bool = True,
        cache_in_process: bool = True,
        cache_on_disk: bool = True,
        docling_page_chunk_size: int | None = 8,
        working_dir: str | Path | None = None,
    ) -> None:
        self.text_fast_path = text_fast_path
        self.cache_in_process = cache_in_process
        self.cache_on_disk = cache_on_disk
        self.docling_page_chunk_size = docling_page_chunk_size
        self.working_dir = Path(working_dir or Path.cwd()).resolve()
        self._converter: Any | None = None
        self._cache: dict[tuple[str, int, int], DocumentText] = {}
        self._docling_runtime_prepared = False

    def parse(self, input_path: str | Path) -> DocumentText:
        path = Path(input_path).resolve()
        if not path.exists() or not path.is_file():
            raise InputLoadError(f"Input file not found: {path}")

        suffix = path.suffix.lower()
        if suffix not in self._SUPPORTED_SUFFIXES:
            raise InputLoadError(
                f"Unsupported input type: {suffix or '(no suffix)'}; "
                f"supported suffixes: {', '.join(sorted(self._SUPPORTED_SUFFIXES))}"
            )

        stat = path.stat()
        cache_key = (str(path), stat.st_size, stat.st_mtime_ns)
        if self.cache_in_process and cache_key in self._cache:
            return self._cache[cache_key].model_copy(deep=True)
        if self.cache_on_disk:
            cached_document = self._load_from_disk_cache(path, stat)
            if cached_document is not None:
                if self.cache_in_process:
                    self._cache[cache_key] = cached_document
                return cached_document.model_copy(deep=True)

        metadata: dict[str, Any] = {
            "file_name": path.name,
            "suffix": suffix,
        }

        if self.text_fast_path and suffix in self._TEXT_FAST_PATH_SUFFIXES:
            text = self._read_plain_text(path)
            parser_backend = "plain-text-fast-path"
        elif suffix == ".pdf":
            text, parser_backend, pdf_metadata = self._parse_pdf(path)
            metadata.update(pdf_metadata)
        else:
            text = self._convert_with_docling(path)
            parser_backend = "docling"

        normalized = self._normalize_text(text)
        if not normalized:
            raise InputLoadError("Input text is empty after parsing")

        document = DocumentText(
            path=str(path),
            input_type=InputType.from_suffix(suffix),
            text=normalized,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            file_size=stat.st_size,
            parser_backend=parser_backend,
            metadata=metadata,
        )
        if self.cache_in_process:
            self._cache[cache_key] = document
        if self.cache_on_disk:
            self._save_to_disk_cache(path, stat, document)
        return document.model_copy(deep=True)

    def capability_report(self) -> dict[str, dict[str, str | bool]]:
        docling_ok = self._docling_available()
        pdfium_ok = self._pdfium_available()
        report: dict[str, dict[str, str | bool]] = {}
        for suffix in sorted(self._SUPPORTED_SUFFIXES):
            if suffix in self._TEXT_FAST_PATH_SUFFIXES and self.text_fast_path:
                report[suffix.lstrip(".")] = {
                    "supported": True,
                    "reason": "plain text fast path is enabled",
                }
                continue
            if suffix == ".pdf":
                supported = pdfium_ok or docling_ok
                reason = (
                    "PDF text fast path or docling converter available"
                    if supported
                    else "neither pypdfium2 nor docling is installed"
                )
                report[suffix.lstrip(".")] = {
                    "supported": supported,
                    "reason": reason,
                }
                continue
            report[suffix.lstrip(".")] = {
                "supported": docling_ok,
                "reason": "docling converter available" if docling_ok else "docling is not installed",
            }
        return report

    def _parse_pdf(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        fast_text, metadata = self._extract_pdf_text_fast(path)
        if fast_text is not None:
            return fast_text, "pdfium-text-fast-path", metadata
        text, docling_metadata = self._convert_pdf_with_docling(path)
        metadata.update(docling_metadata)
        return text, "docling", metadata

    def _convert_with_docling(self, path: Path) -> str:
        result = self._convert_docling_result(path)
        text = self._extract_docling_text_or_empty(result)
        if text:
            return text
        detail = self._describe_docling_result(result) or "Docling returned no text"
        raise InputLoadError(f"Docling failed to parse {path.name}: {detail}")

    def _convert_pdf_with_docling(self, path: Path) -> tuple[str, dict[str, Any]]:
        page_count = self._get_pdf_page_count(path)
        chunk_size = self.docling_page_chunk_size
        if page_count is None or chunk_size is None or page_count <= chunk_size:
            result = self._convert_docling_result(path)
            text = self._extract_docling_text_or_empty(result)
            if not text:
                detail = self._describe_docling_result(result) or "Docling returned no text"
                raise InputLoadError(f"Docling failed to parse {path.name}: {detail}")
            return text, {
                "docling_paged_parse": False,
                "docling_page_chunk_size": chunk_size,
                "docling_page_count": page_count,
            }

        texts: list[str] = []
        failed_ranges: list[list[int]] = []
        partial_ranges: list[list[int]] = []
        ranges: list[list[int]] = []
        error_messages: list[str] = []
        for start_page in range(1, page_count + 1, chunk_size):
            end_page = min(page_count, start_page + chunk_size - 1)
            ranges.append([start_page, end_page])
            result = self._convert_docling_result(path, page_range=(start_page, end_page))
            chunk_text = self._extract_docling_text_or_empty(result)
            if chunk_text:
                texts.append(chunk_text)
            status = getattr(result, "status", None)
            if status is not None and str(status).endswith("PARTIAL_SUCCESS"):
                partial_ranges.append([start_page, end_page])
            if not chunk_text:
                failed_ranges.append([start_page, end_page])
                detail = self._describe_docling_result(result)
                if detail:
                    error_messages.append(f"pages {start_page}-{end_page}: {detail}")

        if not texts:
            detail = "; ".join(error_messages) or "Docling returned no text for all page chunks"
            raise InputLoadError(f"Docling failed to parse {path.name}: {detail}")

        metadata: dict[str, Any] = {
            "docling_paged_parse": True,
            "docling_page_chunk_size": chunk_size,
            "docling_page_count": page_count,
            "docling_page_ranges": ranges,
        }
        if failed_ranges:
            metadata["docling_failed_page_ranges"] = failed_ranges
        if partial_ranges:
            metadata["docling_partial_page_ranges"] = partial_ranges
        if error_messages:
            metadata["docling_chunk_errors"] = error_messages
        return "\n\n".join(texts), metadata

    def _convert_docling_result(
        self,
        path: Path,
        *,
        page_range: tuple[int, int] | None = None,
    ) -> Any:
        converter = self._get_converter()
        try:
            kwargs: dict[str, Any] = {"raises_on_error": False}
            if page_range is not None:
                kwargs["page_range"] = page_range
            result = converter.convert(str(path), **kwargs)
        except Exception as exc:  # pragma: no cover
            detail = str(exc).strip() or exc.__class__.__name__
            raise InputLoadError(f"Docling failed to parse {path.name}: {detail}") from exc
        return result

    def _get_converter(self) -> Any:
        if self._converter is None:
            self._converter = self._build_converter()
        return self._converter

    def _build_converter(self) -> Any:
        try:
            self._prepare_docling_runtime()
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:  # pragma: no cover
            raise InputLoadError(
                "Docling is required for non-plain-text inputs. Install it with `pip install docling`."
            ) from exc
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=PdfPipelineOptions(
                        do_table_structure=False,
                        ocr_batch_size=1,
                        layout_batch_size=1,
                        table_batch_size=1,
                        queue_max_size=8,
                    )
                ),
            }
        )

    def _prepare_docling_runtime(self) -> None:
        if self._docling_runtime_prepared:
            return

        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.settings import settings
        from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel
        from docling.models.stages.table_structure.table_structure_model import TableStructureModel
        from docling.utils.model_downloader import download_models

        cache_dir = self.working_dir / ".cache" / "docling"
        models_dir = cache_dir / "models"
        models_dir.mkdir(parents=True, exist_ok=True)

        settings.cache_dir = cache_dir
        settings.artifacts_path = models_dir

        layout_repo_folder = PdfPipelineOptions().layout_options.model_spec.model_repo_folder
        required_paths = (
            models_dir / layout_repo_folder,
            models_dir / TableStructureModel._model_repo_folder,
            models_dir / RapidOcrModel._model_repo_folder,
        )
        if any(not path.exists() for path in required_paths):
            download_models(
                output_dir=models_dir,
                with_layout=True,
                with_tableformer=True,
                with_tableformer_v2=False,
                with_code_formula=False,
                with_picture_classifier=False,
                with_smolvlm=False,
                with_granitedocling=False,
                with_granitedocling_mlx=False,
                with_smoldocling=False,
                with_smoldocling_mlx=False,
                with_granite_vision=False,
                with_granite_chart_extraction=False,
                with_rapidocr=True,
                with_easyocr=False,
            )

        self._docling_runtime_prepared = True

    def _load_from_disk_cache(self, path: Path, stat: stat_result) -> DocumentText | None:
        cache_path = self._disk_cache_path(path, stat)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("cache_version") != self._DISK_CACHE_VERSION:
                return None
            document = DocumentText.model_validate(payload.get("document", {}))
        except Exception:
            return None

        if document.path != str(path):
            return None
        if not document.text.strip():
            return None
        return document

    def _save_to_disk_cache(self, path: Path, stat: stat_result, document: DocumentText) -> None:
        cache_path = self._disk_cache_path(path, stat)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "cache_version": self._DISK_CACHE_VERSION,
            "document": document.model_dump(mode="json"),
        }
        temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(cache_path)

    def _disk_cache_path(self, path: Path, stat: stat_result) -> Path:
        raw_key = (
            f"v{self._DISK_CACHE_VERSION}|"
            f"{path}|{stat.st_size}|{stat.st_mtime_ns}|{int(self.text_fast_path)}"
        )
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return self._disk_cache_dir() / f"{digest}.json"

    def _disk_cache_dir(self) -> Path:
        return self.working_dir / ".cache" / "parser"

    def _extract_pdf_text_fast(self, path: Path) -> tuple[str | None, dict[str, Any]]:
        metadata: dict[str, Any] = {
            "pdf_text_fast_path": False,
        }
        try:
            import pypdfium2 as pdfium
        except ImportError:
            metadata["pdf_text_fast_path_reason"] = "pypdfium2 is not installed"
            return None, metadata

        try:
            document = pdfium.PdfDocument(str(path))
        except Exception as exc:
            metadata["pdf_text_fast_path_reason"] = f"pypdfium2 could not open the PDF: {exc}"
            return None, metadata
        page_texts: list[str] = []
        nonempty_pages = 0
        non_whitespace_chars = 0

        try:
            total_pages = len(document)
            for index in range(total_pages):
                page = document[index]
                text_page = None
                try:
                    text_page = page.get_textpage()
                    page_text = (text_page.get_text_range() or "").strip()
                finally:
                    if text_page is not None:
                        text_page.close()
                    page.close()

                page_texts.append(page_text)
                if page_text:
                    nonempty_pages += 1
                    non_whitespace_chars += len(re.sub(r"\s+", "", page_text))
        except Exception as exc:
            metadata["pdf_text_fast_path_reason"] = f"pypdfium2 text extraction failed: {exc}"
            return None, metadata
        finally:
            document.close()

        metadata.update(
            {
                "pdf_page_count": total_pages,
                "pdf_text_fast_path_nonempty_pages": nonempty_pages,
                "pdf_text_fast_path_chars": non_whitespace_chars,
            }
        )
        if not self._should_use_pdf_text_fast_path(
            total_pages=total_pages,
            nonempty_pages=nonempty_pages,
            non_whitespace_chars=non_whitespace_chars,
        ):
            metadata["pdf_text_fast_path_reason"] = "embedded text coverage is too low"
            return None, metadata

        metadata["pdf_text_fast_path"] = True
        return "\n\n".join(text for text in page_texts if text), metadata

    def _get_pdf_page_count(self, path: Path) -> int | None:
        try:
            import pypdfium2 as pdfium
        except ImportError:
            return None

        document = None
        try:
            document = pdfium.PdfDocument(str(path))
            return len(document)
        except Exception:
            return None
        finally:
            if document is not None:
                document.close()

    @staticmethod
    def _should_use_pdf_text_fast_path(
        *,
        total_pages: int,
        nonempty_pages: int,
        non_whitespace_chars: int,
    ) -> bool:
        if total_pages <= 0 or nonempty_pages <= 0:
            return False

        coverage_threshold = max(1, (total_pages * 3 + 4) // 5)
        if nonempty_pages >= coverage_threshold:
            return True
        return non_whitespace_chars >= total_pages * 200

    @staticmethod
    def _extract_docling_text(result: Any) -> str:
        document = getattr(result, "document", None)
        if document is None:
            raise InputLoadError("Docling conversion result did not include a document object")

        for method_name in ("export_to_markdown", "export_to_text", "export_to_plain_text"):
            method = getattr(document, method_name, None)
            if callable(method):
                text = method()
                if text:
                    return str(text)

        for attr_name in ("markdown", "text"):
            value = getattr(document, attr_name, None)
            if value:
                return str(value)

        raise InputLoadError("Unable to extract text from Docling conversion result")

    @classmethod
    def _extract_docling_text_or_empty(cls, result: Any) -> str:
        try:
            return cls._extract_docling_text(result)
        except InputLoadError:
            return ""

    @staticmethod
    def _describe_docling_result(result: Any) -> str:
        errors = getattr(result, "errors", None) or []
        messages = [str(getattr(error, "error_message", "")).strip() for error in errors]
        messages = [message for message in messages if message]
        if messages:
            return "; ".join(messages)
        status = getattr(result, "status", None)
        if status is None:
            return ""
        return str(status)

    @staticmethod
    def _read_plain_text(path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="latin-1")

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized

    @staticmethod
    def _docling_available() -> bool:
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _pdfium_available() -> bool:
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            return False
        return True
