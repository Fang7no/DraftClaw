from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from draftclaw._core.exceptions import InputLoadError
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


def test_docling_parser_fast_mode_uses_pypdf_for_pdf(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_text_first") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser(pdf_parse_mode="fast")
    monkeypatch.setattr(parser, "_get_pdf_page_count", lambda _: 2)
    monkeypatch.setattr(parser, "_pypdf_available", lambda: True)
    monkeypatch.setattr(
        parser,
        "_parse_pdf_with_pypdf",
        lambda _path, *, page_count: (
            "page one\n\npage two",
            {
                "pdf_parser_strategy": "pypdf",
                "pdf_page_count": page_count,
                "pdf_nonempty_pages": page_count,
                "pdf_extracted_chars": 1200,
            },
        ),
    )

    document = parser.parse(source)

    assert document.parser_backend == "pypdf"
    assert document.text == "page one\n\npage two"
    assert document.metadata["pdf_page_count"] == 2
    assert document.metadata["pdf_parse_mode"] == "fast"
    assert document.metadata["pdf_parser_strategy"] == "pypdf"


def test_docling_parser_accurate_mode_uses_paddleocr_api(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_sparse_text") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser(
        pdf_parse_mode="accurate",
        paddleocr_api_url="https://ocr.example/api/parse",
        paddleocr_api_key="ocr-key",
        paddleocr_api_model="PaddleOCR-VL-1.5",
    )
    monkeypatch.setattr(parser, "_get_pdf_page_count", lambda _: 2)
    monkeypatch.setattr(
        parser,
        "_parse_pdf_with_paddleocr_api",
        lambda _path, *, page_count: (
            "ocr page one\n\nocr page two",
            {"pdf_parser_strategy": "paddleocr_api"},
        ),
    )

    document = parser.parse(source)

    assert document.parser_backend == "paddleocr-api"
    assert document.text == "ocr page one\n\nocr page two"
    assert document.metadata["pdf_page_count"] == 2
    assert document.metadata["pdf_parse_mode"] == "accurate"
    assert document.metadata["pdf_parser_strategy"] == "paddleocr_api"


def test_docling_parser_fast_mode_requires_pypdf(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_fallback") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser(pdf_parse_mode="fast")
    monkeypatch.setattr(parser, "_get_pdf_page_count", lambda _: 2)
    monkeypatch.setattr(parser, "_pypdf_available", lambda: False)

    with pytest.raises(InputLoadError, match="fast mode requires `pypdf`"):
        parser.parse(source)


def test_docling_parser_accurate_mode_requires_api_url(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_api_url") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser(pdf_parse_mode="accurate")
    monkeypatch.setattr(parser, "_get_pdf_page_count", lambda _: None)

    with pytest.raises(InputLoadError, match="paddleocr_api_url"):
        parser.parse(source)


def test_docling_parser_fast_mode_uses_pypdf_for_long_pdf(monkeypatch) -> None:
    source = _artifact_dir("parser_pdf_pypdf") / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    parser = DoclingDocumentParser(pdf_parse_mode="fast")
    monkeypatch.setattr(parser, "_get_pdf_page_count", lambda _: 40)
    monkeypatch.setattr(
        parser,
        "_parse_pdf_with_pypdf",
        lambda _path, *, page_count: (
            "page one\n\npage forty",
            {"pdf_parser_strategy": "pypdf", "pdf_page_count": page_count, "pdf_nonempty_pages": page_count - 1},
        ),
    )

    document = parser.parse(source)

    assert document.parser_backend == "pypdf"
    assert document.text == "page one\n\npage forty"
    assert document.metadata["pdf_page_count"] == 40
    assert document.metadata["pdf_parser_strategy"] == "pypdf"
    assert document.metadata["pdf_parse_mode"] == "fast"


def test_docling_parser_prepares_project_local_docling_runtime(monkeypatch) -> None:
    settings_module = pytest.importorskip("docling.datamodel.settings")
    settings = settings_module.settings

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

    parser_first = DoclingDocumentParser(
        working_dir=working_dir,
        cache_in_process=False,
        cache_on_disk=True,
        pdf_parse_mode="accurate",
        paddleocr_api_url="https://ocr.example/api/parse",
        paddleocr_api_key="ocr-key",
    )
    parse_calls: list[str] = []

    def fake_paddleocr_api(path: Path, *, page_count: int | None) -> tuple[str, dict[str, object]]:
        parse_calls.append(f"{path.name}:{page_count}")
        return "first parse result", {"pdf_parser_strategy": "paddleocr_api"}

    monkeypatch.setattr(parser_first, "_get_pdf_page_count", lambda _: 2)
    monkeypatch.setattr(parser_first, "_parse_pdf_with_paddleocr_api", fake_paddleocr_api)

    first_document = parser_first.parse(source)

    parser_second = DoclingDocumentParser(
        working_dir=working_dir,
        cache_in_process=False,
        cache_on_disk=True,
        pdf_parse_mode="accurate",
        paddleocr_api_url="https://ocr.example/api/parse",
        paddleocr_api_key="ocr-key",
    )
    monkeypatch.setattr(
        parser_second,
        "_parse_pdf_with_paddleocr_api",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disk cache should avoid re-parsing")),
    )

    second_document = parser_second.parse(source)

    assert parse_calls == ["sample.pdf:2"]
    assert first_document.text == "first parse result"
    assert second_document.text == "first parse result"
    assert second_document.sha256 == first_document.sha256


def test_extract_paddleocr_text_supports_classic_payload() -> None:
    payload = [
        [
            [[[0, 0], [1, 0], [1, 1], [0, 1]], ("first line", 0.99)],
            [[[0, 2], [1, 2], [1, 3], [0, 3]], ("second line", 0.98)],
        ]
    ]

    text = DoclingDocumentParser._extract_paddleocr_text(payload)

    assert text == "first line\nsecond line"


def test_extract_paddleocr_text_supports_structured_payload() -> None:
    payload = [
        {
            "res": {
                "rec_texts": ["alpha", "beta"],
            }
        }
    ]

    text = DoclingDocumentParser._extract_paddleocr_text(payload)

    assert text == "alpha\nbeta"


def test_extract_paddleocr_api_text_supports_jsonl_markdown_payload() -> None:
    payload = "\n".join(
        [
            json.dumps(
                {
                    "result": {
                        "layoutParsingResults": [
                            {"markdown": {"text": "# Page 1\n\nalpha"}},
                            {"markdown": {"text": "beta"}},
                        ]
                    }
                }
            ),
            json.dumps(
                {
                    "result": {
                        "layoutParsingResults": [
                            {"markdown": {"text": "# Page 2\n\ngamma"}},
                        ]
                    }
                }
            ),
        ]
    )

    text, page_count = DoclingDocumentParser._extract_paddleocr_api_text(payload)

    assert text == "# Page 1\n\nalpha\n\nbeta\n\n# Page 2\n\ngamma"
    assert page_count == 3
