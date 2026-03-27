from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from draftclaw._core.contracts import DocumentText
from draftclaw._core.enums import ErrorType, InputType, ModeName
from draftclaw._history.store import HistoryStore
from draftclaw._history.trace import TraceLayout
from draftclaw._modes.deep import DeepMode
from draftclaw._modes.fast import FastMode
from draftclaw._modes.standard import StandardMode
from draftclaw._prompts.builder import PromptBuilder
from draftclaw._resources import package_prompts_root
from draftclaw._runtime.paragraph_chunker import ParagraphChunker


class StubRunner:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)

    async def run_contract(self, *, messages, schema_model, use_repair):  # noqa: ANN001
        payload = self._responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        validated = schema_model.model_validate(payload)
        return validated, json.dumps(payload, ensure_ascii=False), {"stub": True}, False


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _make_history() -> HistoryStore:
    paths = TraceLayout(_artifact_dir("history")).create("run_test")
    return HistoryStore(paths)


def _make_document(text: str) -> DocumentText:
    return DocumentText(
        path="paper.txt",
        input_type=InputType.TXT,
        text=text,
        sha256="sha256",
        file_size=len(text),
        parser_backend="plain-text-fast-path",
        metadata={},
    )


def _prompts_root():
    return package_prompts_root()


@pytest.mark.asyncio
async def test_fast_mode_returns_structured_result() -> None:
    mode = FastMode(
        prompt_builder=PromptBuilder(_prompts_root()),
        chunker=ParagraphChunker(target_chunks=2),
        enable_merge_agent=True,
        llm_runner=StubRunner(
            [
                {
                    "checklist": [
                        {
                            "check_location": "Discussion",
                            "check_explanation": "missing justification for control variable",
                        }
                    ],
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "0.75 + 0.40 = 1.25",
                            "error_type": "Numerical and Calculation Errors",
                            "error_reason": "The arithmetic result in the current sentence is incorrect.",
                            "error_reasoning": "0.75 + 0.40 equals 1.15 rather than 1.25, so the equation contains a confirmed local numerical error.",
                        }
                    ],
                },
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "sample size increases from 100 to 120",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The reported sample size conflicts with the earlier setup in the document.",
                            "error_reasoning": "The previous chunk establishes a sample size of 100 for the same study, but this chunk states 120, so the paper contains a cross-chunk internal inconsistency.",
                        }
                    ],
                },
                {
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "0.75 + 0.40 = 1.25",
                            "error_type": "Numerical and Calculation Errors",
                            "error_reason": "The arithmetic result in the current sentence is incorrect.",
                            "error_reasoning": "0.75 + 0.40 equals 1.15 rather than 1.25, so the equation contains a confirmed local numerical error.",
                        },
                        {
                            "id": 2,
                            "error_location": "sample size increases from 100 to 120",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The reported sample size conflicts with the earlier setup in the document.",
                            "error_reasoning": "The previous chunk establishes a sample size of 100 for the same study, but this chunk states 120, so the paper contains a cross-chunk internal inconsistency.",
                        },
                    ],
                },
            ]
        ),
    )

    result = await mode.run(document=_make_document("p1\n\np2"), history=_make_history())

    assert result.mode == ModeName.FAST
    assert len(result.errorlist) == 2
    assert len(result.checklist) == 1
    assert {item.error_type for item in result.errorlist} == {
        ErrorType.CALCULATION_NUMERICAL_ERROR,
        ErrorType.CONTEXT_MISALIGNMENT,
    }
    assert result.errorlist[0].id == 1
    assert result.errorlist[1].id == 2
    assert result.stats.llm_calls == 4


@pytest.mark.asyncio
async def test_standard_mode_confirms_check_and_merges_errors() -> None:
    mode = StandardMode(
        chunker=ParagraphChunker(target_chunks=2),
        prompt_builder=PromptBuilder(_prompts_root()),
        enable_merge_agent=True,
        llm_runner=StubRunner(
            [
                {
                    "checklist": [
                        {
                            "check_location": "Methods",
                            "check_explanation": "sample size is inconsistent",
                        }
                    ],
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 3,
                            "error_location": "Eq. (2)",
                            "error_type": "Numerical and Calculation Errors",
                            "error_reason": "The arithmetic result written in the equation is incorrect.",
                            "error_reasoning": "The numbers in Eq. (2) do not add up to the stated result, so this chunk contains a confirmed numerical error.",
                        }
                    ],
                },
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 2,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Earlier text defines one sample size for the same experiment, but this chunk reports a different size, so the document is internally inconsistent.",
                        }
                    ],
                },
                {
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 9,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Earlier text defines one sample size for the same experiment, but this chunk reports a different size, so the document is internally inconsistent.",
                        },
                        {
                            "id": 10,
                            "error_location": "Eq. (2)",
                            "error_type": "Numerical and Calculation Errors",
                            "error_reason": "The arithmetic result written in the equation is incorrect.",
                            "error_reasoning": "The numbers in Eq. (2) do not add up to the stated result, so this chunk contains a confirmed numerical error.",
                        },
                    ],
                },
            ]
        ),
    )

    document = _make_document("methods paragraph\n\nresults paragraph")
    result = await mode.run(document=document, history=_make_history())

    assert result.mode == ModeName.STANDARD
    assert len(result.errorlist) == 2
    assert result.errorlist[0].id == 1
    assert result.errorlist[1].id == 2
    assert {item.error_type for item in result.errorlist} == {
        ErrorType.CONTEXT_MISALIGNMENT,
        ErrorType.CALCULATION_NUMERICAL_ERROR,
    }
    assert result.checklist == []
    assert result.stats.rounds == 2
    assert result.stats.llm_calls == 4


@pytest.mark.asyncio
async def test_fast_mode_uses_channel_specific_merge_and_local_combine() -> None:
    history = _make_history()
    mode = FastMode(
        prompt_builder=PromptBuilder(_prompts_root()),
        chunker=ParagraphChunker(target_chunks=2),
        enable_merge_agent=True,
        llm_runner=StubRunner(
            [
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "The earlier chunk and the current chunk report different sample sizes for the same experiment.",
                        }
                    ],
                },
                {
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Table 1 totals 95%",
                            "error_type": "Knowledge Background Errors",
                            "error_reason": "The percentage summary in the current chunk contradicts the stated class totals.",
                            "error_reasoning": "The listed subgroup percentages sum to 100%, but the sentence claims they total 95%, so the statement is factually inconsistent within the chunk.",
                        }
                    ],
                },
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 2,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "The later chunk repeats the same cross-chunk sample-size inconsistency, so the duplicate main-agent findings should merge.",
                        }
                    ],
                },
                {
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 7,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "The repeated main-agent finding describes the same underlying sample-size conflict and should collapse into one issue.",
                        }
                    ],
                },
            ]
        ),
    )

    result = await mode.run(document=_make_document("alpha paragraph\n\nbeta paragraph"), history=history)

    assert len(result.errorlist) == 2
    assert [item.error_location for item in result.errorlist] == ["Methods", "Table 1 totals 95%"]
    assert (history.paths.prompts / "fast_merge_main_1.md").exists()

    prompt_text = (history.paths.prompts / "fast_merge_main_1.md").read_text(encoding="utf-8")
    parsed_text = (history.paths.responses_parsed / "fast_merge_1.json").read_text(encoding="utf-8")

    assert "Methods" in prompt_text
    assert "Table 1 totals 95%" not in prompt_text
    assert "main_context_errorlist" in parsed_text
    assert "local_chunk_errorlist" in parsed_text
    assert "round_reconciled_errorlist" in parsed_text


@pytest.mark.asyncio
async def test_standard_merge_prompts_split_main_and_local_errors() -> None:
    history = _make_history()
    mode = StandardMode(
        chunker=ParagraphChunker(target_chunks=2),
        prompt_builder=PromptBuilder(_prompts_root()),
        enable_merge_agent=True,
        llm_runner=StubRunner(
            [
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Earlier text defines one sample size for the same experiment, but this chunk reports a different size.",
                        }
                    ],
                },
                {
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Eq. (2)",
                            "error_type": "Numerical and Calculation Errors",
                            "error_reason": "The arithmetic result written in the equation is incorrect.",
                            "error_reasoning": "The numbers in Eq. (2) do not add up to the stated result.",
                        }
                    ],
                },
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 2,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Later text reports a different sample size for the same experiment, so the main-agent duplicate should merge.",
                        }
                    ],
                },
                {
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Fig. 3",
                            "error_type": "Language Expression Errors",
                            "error_reason": "The figure caption contains an obvious language issue.",
                            "error_reasoning": "The caption repeats a malformed token, so the sentence contains a confirmed local language error.",
                        }
                    ],
                },
                {
                    "errorlist": [
                        {
                            "id": 9,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "The document reports conflicting sample sizes for the same experiment, so the duplicate main-agent findings should collapse into one issue.",
                        }
                    ],
                },
                {
                    "errorlist": [
                        {
                            "id": 10,
                            "error_location": "Eq. (2)",
                            "error_type": "Numerical and Calculation Errors",
                            "error_reason": "The arithmetic result written in the equation is incorrect.",
                            "error_reasoning": "The numbers in Eq. (2) do not add up to the stated result, so the duplicate local-agent findings should collapse into one issue.",
                        },
                        {
                            "id": 11,
                            "error_location": "Fig. 3",
                            "error_type": "Language Expression Errors",
                            "error_reason": "The figure caption contains an obvious language issue.",
                            "error_reasoning": "The caption repeats a malformed token, so the sentence contains a confirmed local language error.",
                        },
                    ],
                },
            ]
        ),
    )

    result = await mode.run(document=_make_document("methods paragraph\n\nresults paragraph"), history=history)

    assert len(result.errorlist) == 3
    assert [item.error_location for item in result.errorlist] == ["Methods", "Eq. (2)", "Fig. 3"]

    main_prompt_text = (history.paths.prompts / "standard_merge_main_1.md").read_text(encoding="utf-8")
    local_prompt_text = (history.paths.prompts / "standard_merge_local_1.md").read_text(encoding="utf-8")

    assert "Methods" in main_prompt_text
    assert "Eq. (2)" not in main_prompt_text
    assert "Fig. 3" not in main_prompt_text
    assert "Methods" not in local_prompt_text
    assert "Eq. (2)" in local_prompt_text
    assert "Fig. 3" in local_prompt_text


@pytest.mark.asyncio
async def test_standard_mode_drops_final_round_checklist_items() -> None:
    mode = StandardMode(
        chunker=ParagraphChunker(target_chunks=2),
        prompt_builder=PromptBuilder(_prompts_root()),
        llm_runner=StubRunner(
            [
                {
                    "checklist": [
                        {
                            "check_location": "Results",
                            "check_explanation": "numbering may be inconsistent",
                        }
                    ],
                    "errorlist": [],
                },
                {
                    "errorlist": [],
                },
                {
                    "checklist": [
                        {
                            "check_location": "Discussion",
                            "check_explanation": "new concern should not survive final round",
                        }
                    ],
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Fig. 3",
                            "error_type": "Language Expression Errors",
                            "error_reason": "The figure numbering style differs from the rest of the paper.",
                            "error_reasoning": "This chunk uses a figure label format that does not match earlier figure references, so the numbering style is inconsistent.",
                        }
                    ],
                },
            ]
        ),
    )

    document = _make_document("results paragraph\n\ndiscussion paragraph")
    result = await mode.run(document=document, history=_make_history())

    assert result.mode == ModeName.STANDARD
    assert result.checklist == []
    assert len(result.errorlist) == 1
    assert result.errorlist[0].error_type == ErrorType.LANGUAGE_EXPRESSION_ISSUE


@pytest.mark.asyncio
async def test_standard_low_level_prompt_excludes_history_text() -> None:
    history = _make_history()
    mode = StandardMode(
        chunker=ParagraphChunker(target_chunks=2),
        prompt_builder=PromptBuilder(_prompts_root()),
        llm_runner=StubRunner(
            [
                {"checklist": [], "errorlist": []},
                {"errorlist": []},
                {"checklist": [], "errorlist": []},
                {"errorlist": []},
            ]
        ),
    )

    document = _make_document("alpha paragraph\n\nbeta paragraph")
    await mode.run(document=document, history=history)

    prompt_text = (history.paths.prompts / "standard_low_level_2.md").read_text(encoding="utf-8")

    assert "beta paragraph" in prompt_text
    assert "alpha paragraph" not in prompt_text


@pytest.mark.asyncio
async def test_standard_merge_retries_after_validation_failure() -> None:
    from draftclaw._core.exceptions import LLMOutputValidationError

    mode = StandardMode(
        chunker=ParagraphChunker(target_chunks=2),
        prompt_builder=PromptBuilder(_prompts_root()),
        enable_merge_agent=True,
        llm_runner=StubRunner(
            [
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Earlier text defines one sample size, but this chunk reports a different size.",
                        }
                    ],
                },
                {"errorlist": []},
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 2,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Later text reports a different sample size for the same experiment.",
                        }
                    ],
                },
                {"errorlist": []},
                LLMOutputValidationError("bad merge json"),
                {
                    "errorlist": [
                        {
                            "id": 9,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "The document reports conflicting sample sizes for the same experiment, so the duplicate findings should collapse into one issue.",
                        },
                    ],
                },
            ]
        ),
    )

    result = await mode.run(document=_make_document("alpha paragraph\n\nbeta paragraph"), history=_make_history())

    assert result.mode == ModeName.STANDARD
    assert len(result.errorlist) == 1
    assert result.stats.llm_calls == 5


@pytest.mark.asyncio
async def test_fast_mode_supports_auto_chunk_count() -> None:
    mode = FastMode(
        prompt_builder=PromptBuilder(_prompts_root()),
        chunker=ParagraphChunker(target_chunks=0),
        llm_runner=StubRunner(
            [
                {
                    "checklist": [],
                    "errorlist": [],
                },
                {
                    "errorlist": [],
                },
            ]
        ),
    )

    result = await mode.run(document=_make_document("short paragraph"), history=_make_history())

    assert result.mode == ModeName.FAST
    assert result.stats.chunk_count == 1
    assert result.stats.llm_calls == 2


@pytest.mark.asyncio
async def test_standard_mode_supports_auto_chunk_count() -> None:
    mode = StandardMode(
        chunker=ParagraphChunker(target_chunks=0),
        prompt_builder=PromptBuilder(_prompts_root()),
        llm_runner=StubRunner(
            [
                {
                    "checklist": [],
                    "errorlist": [],
                },
                {
                    "errorlist": [],
                },
            ]
        ),
    )

    result = await mode.run(document=_make_document("short paragraph"), history=_make_history())

    assert result.mode == ModeName.STANDARD
    assert result.stats.chunk_count == 1
    assert result.stats.llm_calls == 2


@pytest.mark.asyncio
async def test_deep_mode_runs_three_stage_main_agent_and_preserves_standard_outputs() -> None:
    history = _make_history()
    mode = DeepMode(
        chunker=ParagraphChunker(target_chunks=2),
        prompt_builder=PromptBuilder(_prompts_root()),
        enable_merge_agent=True,
        llm_runner=StubRunner(
            [
                {
                    "plan": [
                        {
                            "focus_location": "Methods",
                            "suspected_issue": "sample size is inconsistent with the earlier setup",
                            "evidence_summary": "The current chunk introduces a different sample size than the earlier setup.",
                        }
                    ],
                },
                {
                    "checklist": [
                        {
                            "check_location": "Methods",
                            "check_explanation": "sample size may conflict with the setup",
                        }
                    ],
                    "errorlist": [],
                },
                {
                    "checklist": [
                        {
                            "check_location": "Methods",
                            "check_explanation": "sample size may conflict with the setup",
                        }
                    ],
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 1,
                            "error_location": "Eq. (2)",
                            "error_type": "Numerical and Calculation Errors",
                            "error_reason": "The arithmetic result written in the equation is incorrect.",
                            "error_reasoning": "The numbers in Eq. (2) do not add up to the stated result, so this chunk contains a confirmed numerical error.",
                        }
                    ],
                },
                {
                    "plan": [
                        {
                            "focus_location": "Methods",
                            "suspected_issue": "confirm the sample-size conflict",
                            "evidence_summary": "Earlier text states one sample size while the current chunk states another.",
                        }
                    ],
                },
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 2,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Earlier text defines one sample size for the same experiment, but this chunk reports a different size, so the document is internally inconsistent.",
                        }
                    ],
                },
                {
                    "checklist": [],
                    "errorlist": [
                        {
                            "id": 2,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "Earlier text defines one sample size for the same experiment, but this chunk reports a different size, so the document is internally inconsistent.",
                        }
                    ],
                },
                {
                    "errorlist": [],
                },
                {
                    "errorlist": [
                        {
                            "id": 9,
                            "error_location": "Methods",
                            "error_type": "Contextual Misalignment",
                            "error_reason": "The sample size is inconsistent with the earlier setup.",
                            "error_reasoning": "The document reports conflicting sample sizes for the same experiment, so the duplicate main-agent findings should collapse into one issue.",
                        }
                    ],
                },
            ]
        ),
    )

    result = await mode.run(document=_make_document("methods paragraph\n\nresults paragraph"), history=history)

    assert result.mode == ModeName.DEEP
    assert result.checklist == []
    assert {item.error_location for item in result.errorlist} == {"Eq. (2)", "Methods"}
    assert result.stats.rounds == 2
    assert result.stats.llm_calls == 8
    assert (history.paths.prompts / "deep_plan_1.md").exists()
    assert (history.paths.prompts / "deep_execute_1.md").exists()
    assert (history.paths.prompts / "deep_validate_1.md").exists()
    assert (history.paths.prompts / "deep_low_level_1.md").exists()
