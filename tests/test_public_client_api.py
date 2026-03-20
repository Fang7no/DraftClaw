from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from draftclaw import DraftClaw, DraftClawSettings, LLMOptions, ModeName, ParserOptions, ReviewOutcome
from draftclaw._core.contracts import DocumentText, ModeResult
from draftclaw._core.enums import InputType


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_public_client_can_parse_text_without_yaml() -> None:
    source = _artifact_dir("client_parse") / "sample.md"
    source.write_text("# Title\r\n\r\nBody", encoding="utf-8")

    client = DraftClaw()

    assert client.parse_text(source) == "# Title\n\nBody"


def test_public_client_review_wraps_run_paths(monkeypatch) -> None:
    source = _artifact_dir("client_review") / "sample.txt"
    source.write_text("alpha\n\nbeta", encoding="utf-8")
    run_dir = _artifact_dir("client_run")

    client = DraftClaw(
        settings=DraftClawSettings(
            llm=LLMOptions(api_key="test-key", base_url="https://example.com/v1", model="demo-model"),
            parser=ParserOptions(text_fast_path=True, cache_in_process=True),
        )
    )

    fake_result = ModeResult(mode=ModeName.FAST)
    monkeypatch.setattr(client._app, "review_sync", lambda **_: (fake_result, run_dir))

    outcome = client.review(source, mode="fast", run_name="demo")

    assert isinstance(outcome, ReviewOutcome)
    assert outcome.result.mode == ModeName.FAST
    assert outcome.run_dir == run_dir.resolve()
    assert outcome.result_json == run_dir.resolve() / "final" / "mode_result.json"
    assert outcome.result_html == run_dir.resolve() / "final" / "mode_result.html"


def test_public_client_run_reuses_parsed_document_for_review(monkeypatch) -> None:
    source = _artifact_dir("client_run_reuse") / "sample.txt"
    source.write_text("alpha\n\nbeta", encoding="utf-8")
    run_dir = _artifact_dir("client_run_reuse_out")

    client = DraftClaw(
        settings=DraftClawSettings(
            llm=LLMOptions(api_key="test-key", base_url="https://example.com/v1", model="demo-model"),
            parser=ParserOptions(text_fast_path=True, cache_in_process=True),
        )
    )
    document = DocumentText(
        path=str(source.resolve()),
        input_type=InputType.TXT,
        text="alpha\n\nbeta",
        sha256="sha256",
        file_size=source.stat().st_size,
        parser_backend="plain-text-fast-path",
        metadata={},
    )
    review_calls: list[DocumentText] = []

    monkeypatch.setattr(client._app, "parse", lambda _: document)

    def fake_review_sync(**kwargs):
        review_calls.append(kwargs["document"])
        return ModeResult(mode=ModeName.FAST), run_dir

    monkeypatch.setattr(client._app, "review_sync", fake_review_sync)

    outcome = client.run(source, review=True, mode="fast", run_name="demo")

    assert outcome.document == document
    assert outcome.review is not None
    assert review_calls == [document]
