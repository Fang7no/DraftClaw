from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from draftclaw import DocumentRun, DocumentText, DraftClaw, DraftClawDocumentParser, parse_document, parse_document_file, parse_document_text, run_document
from draftclaw._core.exceptions import DraftClawError


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_parse_document_is_available_from_package_root() -> None:
    source = _artifact_dir("public_api_root") / "sample.md"
    source.write_text("# Title\r\n\r\nBody", encoding="utf-8")

    document = parse_document(source)

    assert isinstance(document, DocumentText)
    assert document.text == "# Title\n\nBody"
    assert document.input_type.value == "md"


def test_parser_class_is_available_from_package_root() -> None:
    source = _artifact_dir("public_api_class") / "sample.txt"
    source.write_text("alpha\r\n\r\nbeta", encoding="utf-8")

    parser = DraftClawDocumentParser()

    assert parser.parse_text(source) == "alpha\n\nbeta"


def test_root_wrapper_uses_public_draftclaw_api() -> None:
    source = _artifact_dir("public_api_wrapper") / "sample.txt"
    source.write_text("line 1\n\nline 2", encoding="utf-8")

    payload = parse_document_file(source)
    client = DraftClaw.create(api_key="test-key")

    assert payload["parser_backend"] == "plain-text-fast-path"
    assert payload["text"] == "line 1\n\nline 2"
    assert client.parse_text(source) == parse_document_text(source)


def test_run_document_parse_only_returns_document() -> None:
    source = _artifact_dir("public_api_run") / "sample.txt"
    source.write_text("hello", encoding="utf-8")

    outcome = run_document(source, review=False)

    assert isinstance(outcome, DocumentRun)
    assert outcome.document.text == "hello"
    assert outcome.review is None


def test_review_validation_rejects_placeholder_api_key() -> None:
    source = _artifact_dir("public_api_validation") / "sample.txt"
    source.write_text("hello", encoding="utf-8")

    with pytest.raises(DraftClawError, match="API key is not configured"):
        run_document(source, review=True, api_key="your_api_key")
