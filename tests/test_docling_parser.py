from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from docling.datamodel.base_models import ConversionStatus

from draftclaw._io.docling_parser import DoclingDocumentParser


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_docling_parser_uses_text_fast_path_for_txt() -> None:
    source = _artifact_dir("parser_txt") / "sample.txt"
    source.write_text("alpha\r\n\r\nbeta", encoding="utf-8")
    parser = DoclingDocumentParser()

    document = parser.parse(source)

    assert document.parser_backend == "plain-text-fast-path"
    assert document.text == "alpha\n\nbeta"
    assert document.input_type.value == "txt"


def test_docling_parser_uses_docling_for_binary_formats(monkeypatch) -> None:
    class FakeDocument:
        def export_to_markdown(self) -> str:
            return "# Title\n\nBody"

    class FakeConverter:
        def convert(self, source: str, **_: object):
            return SimpleNamespace(document=FakeDocument(), source=source)

    source = _artifact_dir("parser_docx") / "sample.docx"
    source.write_bytes(b"fake-docx")
    parser = DoclingDocumentParser()
    monkeypatch.setattr(parser, "_build_converter", lambda: FakeConverter())

    document = parser.parse(source)

    assert document.parser_backend == "docling"
    assert document.input_type.value == "docx"
    assert "# Title" in document.text


def test_docling_parser_uses_pdfium_fast_path_for_pdf(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_fast") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser()
    monkeypatch.setattr(
        parser,
        "_extract_pdf_text_fast",
        lambda _: ("page one\n\npage two", {"pdf_text_fast_path": True, "pdf_page_count": 2}),
    )
    monkeypatch.setattr(
        parser,
        "_convert_with_docling",
        lambda _: (_ for _ in ()).throw(AssertionError("pdf fast path should avoid docling")),
    )

    document = parser.parse(source)

    assert document.parser_backend == "pdfium-text-fast-path"
    assert document.text == "page one\n\npage two"
    assert document.metadata["pdf_text_fast_path"] is True
    assert document.metadata["pdf_page_count"] == 2


def test_docling_parser_falls_back_to_docling_when_pdfium_text_is_insufficient(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_docling_fallback") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser()
    monkeypatch.setattr(
        parser,
        "_extract_pdf_text_fast",
        lambda _: (
            None,
            {
                "pdf_text_fast_path": False,
                "pdf_text_fast_path_reason": "embedded text coverage is too low",
            },
        ),
    )
    monkeypatch.setattr(
        parser,
        "_convert_pdf_with_docling",
        lambda _: (
            "docling fallback text",
            {"docling_paged_parse": False, "docling_page_chunk_size": 8},
        ),
    )

    document = parser.parse(source)

    assert document.parser_backend == "docling"
    assert document.text == "docling fallback text"
    assert document.metadata["pdf_text_fast_path"] is False
    assert document.metadata["pdf_text_fast_path_reason"] == "embedded text coverage is too low"
    assert document.metadata["docling_paged_parse"] is False


def test_docling_parser_prepares_project_local_docling_runtime(monkeypatch) -> None:
    from docling.datamodel.settings import settings

    calls: list[dict[str, object]] = []

    def fake_download_models(**kwargs):
        calls.append(kwargs)
        return kwargs["output_dir"]

    original_cache_dir = settings.cache_dir
    original_artifacts_path = settings.artifacts_path
    working_dir = _artifact_dir("parser_runtime")
    parser = DoclingDocumentParser(working_dir=working_dir)
    monkeypatch.setattr("docling.utils.model_downloader.download_models", fake_download_models)

    expected_cache_dir = working_dir.resolve() / ".cache" / "docling"
    expected_models_dir = expected_cache_dir / "models"
    try:
        parser._prepare_docling_runtime()
        prepared_cache_dir = settings.cache_dir
        prepared_artifacts_path = settings.artifacts_path
        parser._prepare_docling_runtime()
    finally:
        settings.cache_dir = original_cache_dir
        settings.artifacts_path = original_artifacts_path

    assert prepared_cache_dir == expected_cache_dir
    assert prepared_artifacts_path == expected_models_dir
    assert settings.cache_dir == original_cache_dir
    assert settings.artifacts_path == original_artifacts_path
    assert expected_models_dir.exists()
    assert len(calls) == 1
    assert calls[0] == {
        "output_dir": expected_models_dir,
        "with_layout": True,
        "with_tableformer": True,
        "with_tableformer_v2": False,
        "with_code_formula": False,
        "with_picture_classifier": False,
        "with_smolvlm": False,
        "with_granitedocling": False,
        "with_granitedocling_mlx": False,
        "with_smoldocling": False,
        "with_smoldocling_mlx": False,
        "with_granite_vision": False,
        "with_granite_chart_extraction": False,
        "with_rapidocr": True,
        "with_easyocr": False,
    }
    assert parser._docling_runtime_prepared is True


def test_docling_parser_reuses_disk_cache_across_instances(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_cache") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    working_dir = _artifact_dir("parser_pdf_cache_workdir")

    parser_first = DoclingDocumentParser(working_dir=working_dir, cache_in_process=False, cache_on_disk=True)
    parse_calls: list[str] = []

    def fake_convert(path: Path) -> tuple[str, dict[str, object]]:
        parse_calls.append(path.name)
        return "first parse result", {"docling_paged_parse": False}

    monkeypatch.setattr(parser_first, "_extract_pdf_text_fast", lambda _: (None, {"pdf_text_fast_path": False}))
    monkeypatch.setattr(parser_first, "_convert_pdf_with_docling", fake_convert)

    first_document = parser_first.parse(source)

    parser_second = DoclingDocumentParser(working_dir=working_dir, cache_in_process=False, cache_on_disk=True)
    monkeypatch.setattr(
        parser_second,
        "_convert_pdf_with_docling",
        lambda _: (_ for _ in ()).throw(AssertionError("disk cache should avoid re-parsing")),
    )

    second_document = parser_second.parse(source)

    assert parse_calls == ["sample.pdf"]
    assert first_document.text == "first parse result"
    assert second_document.text == "first parse result"
    assert second_document.sha256 == first_document.sha256


def test_docling_parser_chunks_docling_pdf_conversion(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_chunked") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser(docling_page_chunk_size=2)
    calls: list[tuple[int, int] | None] = []

    class FakeDocument:
        def __init__(self, text: str) -> None:
            self._text = text

        def export_to_markdown(self) -> str:
            return self._text

    class FakeConverter:
        def convert(self, source: str, **kwargs):
            page_range = kwargs.get("page_range")
            calls.append(page_range)
            if page_range == (3, 4):
                return SimpleNamespace(
                    document=FakeDocument("chunk 3-4"),
                    status=ConversionStatus.PARTIAL_SUCCESS,
                    errors=[SimpleNamespace(error_message="Page 4: std::bad_alloc")],
                )
            return SimpleNamespace(
                document=FakeDocument(f"chunk {page_range[0]}-{page_range[1]}"),
                status=ConversionStatus.SUCCESS,
                errors=[],
            )

    monkeypatch.setattr(parser, "_get_converter", lambda: FakeConverter())
    monkeypatch.setattr(parser, "_get_pdf_page_count", lambda _: 5)

    text, metadata = parser._convert_pdf_with_docling(source)

    assert text == "chunk 1-2\n\nchunk 3-4\n\nchunk 5-5"
    assert calls == [(1, 2), (3, 4), (5, 5)]
    assert metadata["docling_paged_parse"] is True
    assert metadata["docling_page_chunk_size"] == 2
    assert metadata["docling_page_ranges"] == [[1, 2], [3, 4], [5, 5]]
    assert metadata["docling_partial_page_ranges"] == [[3, 4]]


def test_pdf_fast_path_heuristic_requires_reasonable_coverage() -> None:
    assert DoclingDocumentParser._should_use_pdf_text_fast_path(
        total_pages=10,
        nonempty_pages=7,
        non_whitespace_chars=700,
    )
    assert not DoclingDocumentParser._should_use_pdf_text_fast_path(
        total_pages=10,
        nonempty_pages=2,
        non_whitespace_chars=400,
    )
