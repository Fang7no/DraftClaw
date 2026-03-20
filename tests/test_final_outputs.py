from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from draftclaw._core.contracts import DocumentText, ModeResult
from draftclaw._core.enums import ErrorType, InputType, ModeName
from draftclaw._history.store import HistoryStore
from draftclaw._history.trace import TraceLayout


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _make_history() -> HistoryStore:
    paths = TraceLayout(_artifact_dir("final_outputs")).create("run_test")
    return HistoryStore(paths)


def _make_document() -> DocumentText:
    text = "Alpha result has teh typo.\n\nMethods report n=120 here.\n\nEarlier setup declared n=100."
    return DocumentText(
        path="paper.txt",
        input_type=InputType.TXT,
        text=text,
        sha256="sha256",
        file_size=len(text),
        parser_backend="plain-text-fast-path",
        metadata={},
    )


def test_final_outputs_group_errors_and_write_html() -> None:
    history = _make_history()
    document = _make_document()
    result = ModeResult.model_validate(
        {
            "mode": ModeName.STANDARD,
            "errorlist": [
                {
                    "id": 9,
                    "error_location": "Methods report n=120 here.",
                    "error_type": ErrorType.CONTEXT_MISALIGNMENT,
                    "error_reason": "The sample size conflicts with another section.",
                    "error_reasoning": "One paragraph reports n=120 while another states n=100 for the same setup.",
                },
                {
                    "id": 3,
                    "error_location": "teh",
                    "error_type": ErrorType.LANGUAGE_EXPRESSION_ISSUE,
                    "error_reason": "The token is misspelled.",
                    "error_reasoning": "The word should be 'the', so this is a confirmed spelling issue.",
                },
                {
                    "id": 1,
                    "error_location": "Earlier setup declared n=100.",
                    "error_type": ErrorType.EXPERIMENT_PROTOCOL_DEFECT,
                    "error_reason": "The setup specification is inconsistent.",
                    "error_reasoning": "The paper gives conflicting setup values, which makes the procedure operationally unclear.",
                },
            ],
            "final_summary": "Three confirmed issues.",
        }
    )

    json_path, md_path, html_path = history.save_final_result(
        result,
        document,
        json_name="mode_result.json",
        md_name="mode_result.md",
        html_name="mode_result.html",
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")

    assert [item["error_type"] for item in payload["errorlist"]] == [
        ErrorType.LANGUAGE_EXPRESSION_ISSUE.value,
        ErrorType.EXPERIMENT_PROTOCOL_DEFECT.value,
        ErrorType.CONTEXT_MISALIGNMENT.value,
    ]
    assert [item["id"] for item in payload["errorlist"]] == [1, 2, 3]
    assert payload["error_groups"][0]["error_type"] == "Language Expression Errors"
    assert payload["error_groups"][0]["error_count"] == 1
    assert payload["error_groups"][4]["error_type"] == "Experimental Operational Defects"
    assert payload["error_groups"][4]["error_count"] == 1
    assert payload["error_groups"][7]["error_type"] == "Contextual Misalignment"
    assert payload["error_groups"][7]["error_count"] == 1

    assert markdown.index("语言表达错误: 1") < markdown.index("上下文不一致: 1")
    assert "## 错误分组" in markdown
    assert "### 语言表达错误（1）" in markdown

    assert "分组错误导航" in html
    assert "语言表达错误" in html
    assert "上下文不一致" in html
    assert "<h1>paper.txt</h1>" in html
    assert "Alpha result has teh typo." in html
