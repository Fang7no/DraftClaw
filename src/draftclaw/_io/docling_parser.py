from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import OrderedDict
from os import stat_result
from pathlib import Path
from time import monotonic, sleep
from typing import Any

import httpx

from draftclaw._core.contracts import DocumentText
from draftclaw._core.enums import InputType
from draftclaw._core.exceptions import InputLoadError


class DoclingDocumentParser:
    _DISK_CACHE_VERSION = 5
    _TEXT_FAST_PATH_SUFFIXES = {".txt", ".md"}
    _DOCLING_SUFFIXES = {".pdf", ".docx", ".pptx", ".html", ".htm", ".adoc", ".asciidoc"}
    _SUPPORTED_SUFFIXES = _TEXT_FAST_PATH_SUFFIXES | _DOCLING_SUFFIXES
    _MAX_CACHE_SIZE = 100

    def __init__(
        self,
        *,
        text_fast_path: bool = True,
        cache_in_process: bool = True,
        cache_on_disk: bool = True,
        docling_page_chunk_size: int | None = 8,
        pdf_parse_mode: str = "fast",
        paddleocr_api_url: str = "",
        paddleocr_api_key: str = "",
        paddleocr_api_model: str = "PaddleOCR-VL-1.5",
        paddleocr_poll_interval_sec: float = 5.0,
        paddleocr_api_timeout_sec: float = 120.0,
        working_dir: str | Path | None = None,
    ) -> None:
        self.text_fast_path = text_fast_path
        self.cache_in_process = cache_in_process
        self.cache_on_disk = cache_on_disk
        self.docling_page_chunk_size = docling_page_chunk_size
        self.pdf_parse_mode = str(pdf_parse_mode or "fast").strip().lower() or "fast"
        self.paddleocr_api_url = paddleocr_api_url
        self.paddleocr_api_key = paddleocr_api_key
        self.paddleocr_api_model = paddleocr_api_model
        self.paddleocr_poll_interval_sec = float(paddleocr_poll_interval_sec)
        self.paddleocr_api_timeout_sec = float(paddleocr_api_timeout_sec)
        self.working_dir = Path(working_dir or Path.cwd()).resolve()
        self._converter: Any | None = None
        self._cache: OrderedDict[tuple[str, int, int], DocumentText] = OrderedDict()
        self._docling_runtime_prepared = False
        self._capability_report: dict[str, dict[str, str | bool]] | None = None

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
            self._cache.move_to_end(cache_key)
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
            sha256=self._hash_file(path),
            file_size=stat.st_size,
            parser_backend=parser_backend,
            metadata=metadata,
        )
        if self.cache_in_process:
            if len(self._cache) >= self._MAX_CACHE_SIZE:
                self._cache.popitem(last=False)
            self._cache[cache_key] = document
        if self.cache_on_disk:
            self._save_to_disk_cache(path, stat, document)
        return document.model_copy(deep=True)

    def capability_report(self) -> dict[str, dict[str, str | bool]]:
        if self._capability_report is not None:
            return self._capability_report
        docling_ok = self._docling_available()
        pypdf_ok = self._pypdf_available()
        accurate_mode_ready = self._paddleocr_api_ready()
        report: dict[str, dict[str, str | bool]] = {}
        for suffix in sorted(self._SUPPORTED_SUFFIXES):
            if suffix in self._TEXT_FAST_PATH_SUFFIXES and self.text_fast_path:
                report[suffix.lstrip(".")] = {
                    "supported": True,
                    "reason": "plain text fast path is enabled",
                }
                continue
            if suffix == ".pdf":
                if self.pdf_parse_mode == "accurate":
                    supported = accurate_mode_ready
                    if supported:
                        reason = "PDF parsing uses the PaddleOCR jobs API in accurate mode"
                    else:
                        reason = "accurate PDF mode requires both parser.paddleocr_api_url and parser.paddleocr_api_key"
                else:
                    supported = pypdf_ok
                    reason = (
                        "PDF parsing uses local pypdf text extraction in fast mode"
                        if supported
                        else "missing required PDF dependency: pypdf"
                    )
                report[suffix.lstrip(".")] = {
                    "supported": supported,
                    "reason": reason,
                }
                continue
            report[suffix.lstrip(".")] = {
                "supported": docling_ok,
                "reason": "local docling converter available" if docling_ok else "docling is not installed",
            }
        self._capability_report = report
        return report

    def _parse_pdf(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        if path.stat().st_size <= 0:
            raise InputLoadError(f"PDF file is empty: {path.name}. Please upload the file again.")

        page_count = self._get_pdf_page_count(path)
        metadata: dict[str, Any] = {
            "pdf_parse_mode": self.pdf_parse_mode,
        }
        if page_count is not None and page_count > 0:
            metadata["pdf_page_count"] = page_count

        if self.pdf_parse_mode == "accurate":
            text, ocr_metadata = self._parse_pdf_with_paddleocr_api(path, page_count=page_count)
            metadata.update(ocr_metadata)
            return text, "paddleocr-api", metadata

        if not self._pypdf_available():
            raise InputLoadError("PDF fast mode requires `pypdf`. Install it with `pip install pypdf`.")

        text, pypdf_metadata = self._parse_pdf_with_pypdf(path, page_count=page_count)
        metadata.update(pypdf_metadata)
        return text, "pypdf", metadata

    def _parse_pdf_with_paddleocr_api(self, path: Path, *, page_count: int | None) -> tuple[str, dict[str, Any]]:
        api_url = self.paddleocr_api_url.strip()
        if not api_url:
            raise InputLoadError("PDF accurate mode requires `parser.paddleocr_api_url`.")
        api_key = self.paddleocr_api_key.strip()
        if not api_key or api_key == "***":
            raise InputLoadError("PDF accurate mode requires `parser.paddleocr_api_key`.")
        model = self.paddleocr_api_model.strip() or "PaddleOCR-VL-1.5"

        headers = {
            "Accept": "application/json",
            "Authorization": f"bearer {api_key}",
        }
        payload = {
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }
        data = {
            "model": model,
            "optionalPayload": json.dumps(payload, ensure_ascii=False),
        }

        request_timeout = min(max(self.paddleocr_poll_interval_sec + 10.0, 20.0), self.paddleocr_api_timeout_sec)

        try:
            with path.open("rb") as handle, httpx.Client(timeout=request_timeout, follow_redirects=True) as client:
                submit_response = client.post(
                    api_url,
                    headers=headers,
                    data=data,
                    files={"file": (path.name, handle, "application/pdf")},
                )
                submit_response.raise_for_status()
                submit_payload = self._decode_paddleocr_api_payload(submit_response)
                job_id = self._extract_paddleocr_job_id(submit_payload)
                status_payload = self._poll_paddleocr_job(client, api_url, headers=headers, job_id=job_id)
                jsonl_url = self._extract_paddleocr_result_url(status_payload)
                jsonl_response = client.get(jsonl_url)
                jsonl_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() or exc.response.reason_phrase
            raise InputLoadError(f"PaddleOCR API rejected {path.name}: {detail}") from exc
        except httpx.TimeoutException as exc:
            raise InputLoadError(
                f"PaddleOCR API timed out while parsing {path.name} after {self.paddleocr_api_timeout_sec:.0f} seconds."
            ) from exc
        except httpx.HTTPError as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            raise InputLoadError(f"PaddleOCR API request failed for {path.name}: {detail}") from exc

        text, extracted_pages = self._extract_paddleocr_api_text(jsonl_response.text)
        if not text:
            raise InputLoadError(f"PaddleOCR API returned no text for {path.name}.")

        metadata: dict[str, Any] = {
            "pdf_parser_strategy": "paddleocr_api",
            "pdf_parser_job_url": api_url,
            "pdf_parser_model": model,
        }
        if page_count is not None and page_count > 0:
            metadata["pdf_page_count"] = page_count
        if extracted_pages is not None:
            metadata["pdf_nonempty_pages"] = extracted_pages
        request_id = self._extract_paddleocr_request_id(status_payload)
        if request_id:
            metadata["pdf_parser_request_id"] = request_id
        metadata["pdf_parser_job_id"] = job_id
        return text, metadata

    def _parse_pdf_with_pypdf(self, path: Path, *, page_count: int | None) -> tuple[str, dict[str, Any]]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise InputLoadError("PDF fast mode requires `pypdf`. Install it with `pip install pypdf`.") from exc

        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            raise InputLoadError(f"pypdf could not open {path.name}: {detail}") from exc

        resolved_page_count = page_count if page_count is not None and page_count > 0 else len(reader.pages)
        page_texts: list[str] = []
        nonempty_pages = 0
        non_whitespace_chars = 0
        for index, page in enumerate(reader.pages[:resolved_page_count], start=1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception as exc:
                detail = str(exc).strip() or exc.__class__.__name__
                raise InputLoadError(f"pypdf failed to extract page {index} from {path.name}: {detail}") from exc
            page_texts.append(page_text)
            if page_text:
                nonempty_pages += 1
                non_whitespace_chars += len(re.sub(r"\s+", "", page_text))

        if nonempty_pages <= 0:
            raise InputLoadError(f"pypdf failed to extract text from {path.name}: no page returned readable text")

        return "\n\n".join(text for text in page_texts if text), {
            "pdf_parser_strategy": "pypdf",
            "pdf_page_count": resolved_page_count,
            "pdf_nonempty_pages": nonempty_pages,
            "pdf_extracted_chars": non_whitespace_chars,
        }

    def _convert_with_docling(self, path: Path) -> str:
        result = self._convert_docling_result(path)
        text = self._extract_docling_text_or_empty(result)
        if text:
            return text
        detail = self._describe_docling_result(result) or "Docling returned no text"
        raise InputLoadError(f"Docling failed to parse {path.name}: {detail}")

    def _convert_docling_result(self, path: Path) -> Any:
        converter = self._get_converter()
        try:
            return converter.convert(str(path), raises_on_error=False)
        except Exception as exc:  # pragma: no cover
            detail = str(exc).strip() or exc.__class__.__name__
            raise InputLoadError(f"Docling failed to parse {path.name}: {detail}") from exc

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

    @staticmethod
    def _decode_paddleocr_api_payload(response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "").lower()
        if "json" in content_type:
            try:
                return response.json()
            except ValueError:
                return response.text
        body = response.text
        stripped = body.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return response.json()
            except ValueError:
                return body
        return body

    @classmethod
    def _extract_paddleocr_job_id(cls, payload: Any) -> str:
        if not isinstance(payload, dict):
            raise InputLoadError("PaddleOCR API submit response did not return JSON data.")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InputLoadError("PaddleOCR API submit response is missing `data`.")
        job_id = data.get("jobId")
        if not isinstance(job_id, str) or not job_id.strip():
            raise InputLoadError("PaddleOCR API submit response is missing `data.jobId`.")
        return job_id.strip()

    def _poll_paddleocr_job(
        self,
        client: httpx.Client,
        job_url: str,
        *,
        headers: dict[str, str],
        job_id: str,
    ) -> Any:
        deadline = monotonic() + self.paddleocr_api_timeout_sec
        last_state = ""
        status_url = f"{job_url.rstrip('/')}/{job_id}"
        while True:
            if monotonic() > deadline:
                raise InputLoadError(
                    f"PaddleOCR API timed out while waiting for job {job_id} after {self.paddleocr_api_timeout_sec:.0f} seconds."
                )
            response = client.get(status_url, headers=headers)
            response.raise_for_status()
            payload = self._decode_paddleocr_api_payload(response)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise InputLoadError("PaddleOCR API status response is missing `data`.")
            state = str(data.get("state") or "").strip().lower()
            if state == "done":
                return payload
            if state == "failed":
                error_msg = data.get("errorMsg")
                detail = str(error_msg).strip() if error_msg else "unknown error"
                raise InputLoadError(f"PaddleOCR API job failed: {detail}")
            if state not in {"pending", "running"}:
                raise InputLoadError(f"PaddleOCR API returned an unexpected job state: {state or 'unknown'}")
            if state != last_state:
                last_state = state
            sleep(self.paddleocr_poll_interval_sec)

    @staticmethod
    def _extract_paddleocr_result_url(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise InputLoadError("PaddleOCR API status response did not return JSON data.")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InputLoadError("PaddleOCR API status response is missing `data`.")
        result_url = data.get("resultUrl")
        if not isinstance(result_url, dict):
            raise InputLoadError("PaddleOCR API status response is missing `data.resultUrl`.")
        json_url = result_url.get("jsonUrl") or result_url.get("jsonlUrl")
        if not isinstance(json_url, str) or not json_url.strip():
            raise InputLoadError("PaddleOCR API status response is missing `data.resultUrl.jsonUrl`.")
        return json_url.strip()

    @staticmethod
    def _extract_paddleocr_request_id(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        for key in ("requestId", "request_id", "traceId", "trace_id"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _extract_paddleocr_api_text(cls, payload: Any) -> tuple[str, int | None]:
        if isinstance(payload, str):
            stripped = payload.strip()
            if not stripped:
                return "", None
            markdown_pages: list[str] = []
            page_count = 0
            for raw_line in stripped.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    line_payload = json.loads(line)
                except ValueError:
                    markdown_pages.append(line)
                    continue
                line_texts = cls._extract_paddleocr_jsonl_line_text(line_payload)
                if line_texts:
                    markdown_pages.extend(line_texts)
                    page_count += len(line_texts)
            return "\n\n".join(text for text in markdown_pages if text.strip()).strip(), (page_count or None)
        if isinstance(payload, dict):
            for key in ("text", "content", "markdown", "md"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip(), None
        return cls._extract_paddleocr_text(payload).strip(), None

    @classmethod
    def _extract_paddleocr_jsonl_line_text(cls, payload: Any) -> list[str]:
        if not isinstance(payload, dict):
            extracted = cls._extract_paddleocr_text(payload).strip()
            return [extracted] if extracted else []
        result = payload.get("result")
        if not isinstance(result, dict):
            extracted = cls._extract_paddleocr_text(payload).strip()
            return [extracted] if extracted else []
        layout_results = result.get("layoutParsingResults")
        if not isinstance(layout_results, list):
            extracted = cls._extract_paddleocr_text(result).strip()
            return [extracted] if extracted else []
        fragments: list[str] = []
        for item in layout_results:
            if not isinstance(item, dict):
                continue
            markdown = item.get("markdown")
            if isinstance(markdown, dict):
                text = markdown.get("text")
                if isinstance(text, str) and text.strip():
                    fragments.append(text.strip())
        if fragments:
            return fragments
        extracted = cls._extract_paddleocr_text(result).strip()
        return [extracted] if extracted else []

    @classmethod
    def _extract_paddleocr_text(cls, result: Any) -> str:
        fragments: list[str] = []
        cls._collect_paddleocr_fragments(result, fragments)
        return "\n".join(fragment for fragment in fragments if fragment)

    @classmethod
    def _collect_paddleocr_fragments(cls, node: Any, fragments: list[str]) -> None:
        if node is None:
            return
        if isinstance(node, str):
            text = node.strip()
            if text:
                fragments.append(text)
            return
        if isinstance(node, dict):
            for key in ("text", "rec_text", "transcription", "label"):
                value = node.get(key)
                if isinstance(value, str):
                    text = value.strip()
                    if text:
                        fragments.append(text)
            for key in ("texts", "rec_texts", "transcriptions", "labels"):
                value = node.get(key)
                if isinstance(value, (list, tuple)):
                    for item in value:
                        cls._collect_paddleocr_fragments(item, fragments)
            for key in ("res", "result", "results", "pages", "data", "output"):
                if key in node:
                    cls._collect_paddleocr_fragments(node.get(key), fragments)
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[1], (list, tuple)) and node[1]:
                candidate = node[1][0]
                if isinstance(candidate, str):
                    text = candidate.strip()
                    if text:
                        fragments.append(text)
                    return
            for item in node:
                cls._collect_paddleocr_fragments(item, fragments)

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
            f"{path}|{stat.st_size}|{stat.st_mtime_ns}|{int(self.text_fast_path)}|"
            f"{self.pdf_parse_mode}|{self.paddleocr_api_url.strip()}|{self.paddleocr_api_key.strip()}|"
            f"{self.paddleocr_api_model.strip()}"
        )
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return self._disk_cache_dir() / f"{digest}.json"

    def _disk_cache_dir(self) -> Path:
        return self.working_dir / ".cache" / "parser"

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _get_pdf_page_count(self, path: Path) -> int | None:
        try:
            from pypdf import PdfReader
        except ImportError:
            PdfReader = None

        if PdfReader is not None:
            try:
                reader = PdfReader(str(path))
                return len(reader.pages)
            except Exception:
                pass

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
        return DoclingDocumentParser._module_available("docling.document_converter")

    @staticmethod
    def _pypdf_available() -> bool:
        return DoclingDocumentParser._module_available("pypdf")

    def _paddleocr_api_ready(self) -> bool:
        return (
            self.paddleocr_api_url.strip().startswith(("http://", "https://"))
            and bool(self.paddleocr_api_key.strip())
            and self.paddleocr_api_key.strip() != "***"
            and bool(self.paddleocr_api_model.strip())
        )

    @staticmethod
    def _module_available(module_name: str) -> bool:
        try:
            return importlib.util.find_spec(module_name) is not None
        except ModuleNotFoundError:
            return False
