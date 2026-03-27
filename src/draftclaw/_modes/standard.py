from __future__ import annotations

import asyncio
import json
from time import perf_counter

from draftclaw._core.contracts import CheckItem, DocumentText, ErrorItem, ErrorMergeOutput, LLMRoundOutput, ModeResult, ModeStats
from draftclaw._core.enums import ErrorType, ModeName
from draftclaw._core.exceptions import LLMOutputValidationError, LLMRequestError
from draftclaw._history.store import HistoryStore
from draftclaw._postprocess.dedup import renumber_error_items
from draftclaw._postprocess.reconcile import reconcile_round
from draftclaw._prompts.builder import PromptBuilder
from draftclaw._runtime.paragraph_chunker import ParagraphChunker
from draftclaw._runtime.progress import (
    PROGRESS_STAGE_ANALYZING,
    PROGRESS_STAGE_REPORTING,
    ProgressCallback,
    chunk_progress_detail,
    emit_progress,
)


MAIN_CONTEXT_ERROR_TYPES = frozenset(
    {
        ErrorType.METHOD_LOGIC_ERROR,
        ErrorType.EXPERIMENT_PROTOCOL_DEFECT,
        ErrorType.MEASUREMENT_OPERATIONALIZATION_ISSUE,
        ErrorType.CLAIM_DISTORTION,
        ErrorType.CITATION_FABRICATION,
        ErrorType.CONTEXT_MISALIGNMENT,
        ErrorType.TEXT_FIGURE_MISMATCH,
    }
)
LOCAL_CHUNK_ERROR_TYPES = frozenset(
    {
        ErrorType.LANGUAGE_EXPRESSION_ISSUE,
        ErrorType.FACTUAL_ERROR,
        ErrorType.CALCULATION_NUMERICAL_ERROR,
    }
)


class StandardMode:
    def __init__(
        self,
        *,
        chunker: ParagraphChunker,
        prompt_builder: PromptBuilder,
        llm_runner,
        enable_merge_agent: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.chunker = chunker
        self.prompt_builder = prompt_builder
        self.llm_runner = llm_runner
        self.enable_merge_agent = enable_merge_agent
        self._progress_callback = progress_callback

    async def run(self, *, document: DocumentText, history: HistoryStore) -> ModeResult:
        mode_start = perf_counter()

        chunks, infos = self.chunker.split(document.text)
        history.save_chunks(chunks, infos)
        total_rounds = len(chunks)
        self._report_agent_progress(current=0, total=total_rounds)

        checklist: list[CheckItem] = []
        state_errorlist: list[ErrorItem] = []
        main_error_batches: list[tuple[str, list[ErrorItem]]] = []
        low_level_error_batches: list[tuple[str, list[ErrorItem]]] = []
        llm_calls = 0

        for round_no in range(1, total_rounds + 1):
            current_chunk = chunks[round_no - 1]
            history_text = "\n\n".join(chunks[: round_no - 1])
            is_final_round = round_no == total_rounds
            main_messages, main_rendered = self.prompt_builder.build_messages(
                system_files=[
                    "system/base_guardrails.md",
                    "system/json_only_contract.md",
                ],
                user_file="modes/standard_round.md",
                variables={
                    "round_no": round_no,
                    "total_rounds": total_rounds,
                    "is_final_round": is_final_round,
                    "current_chunk_text": current_chunk,
                    "history_text": history_text,
                    "checklist_json": self._compact_checklist_json(checklist),
                },
            )
            low_level_messages, low_level_rendered = self.prompt_builder.build_messages(
                system_files=[
                    "system/low_level_quality_guardrails.md",
                    "system/error_merge_json_contract.md",
                ],
                user_file="modes/standard_low_level_round.md",
                variables={
                    "round_no": round_no,
                    "total_rounds": total_rounds,
                    "current_chunk_text": current_chunk,
                },
            )
            history.save_prompt("standard_main", round_no, main_rendered)
            history.save_prompt("standard_low_level", round_no, low_level_rendered)

            (parsed_main, raw_main, main_elapsed_ms), (parsed_low_level, raw_low_level, low_level_elapsed_ms) = (
                await asyncio.gather(
                    self._run_stage(messages=main_messages, schema_model=LLMRoundOutput),
                    self._run_stage(messages=low_level_messages, schema_model=ErrorMergeOutput),
                )
            )
            llm_calls += 2

            history.save_timing(
                stage="standard_main_llm",
                step=round_no,
                elapsed_ms=main_elapsed_ms,
                details={
                    "input_chars": len(current_chunk),
                    "history_chars": len(history_text),
                    "check_items_in": len(checklist),
                    "new_errors": len(parsed_main.errorlist),
                    "new_checks": len(parsed_main.checklist),
                },
            )
            history.save_timing(
                stage="standard_low_level_llm",
                step=round_no,
                elapsed_ms=low_level_elapsed_ms,
                details={
                    "input_chars": len(current_chunk),
                    "history_chars": len(history_text),
                    "new_errors": len(parsed_low_level.errorlist),
                },
            )
            history.save_raw_response("standard_main", round_no, raw_main)
            history.save_parsed_response("standard_main", round_no, parsed_main.model_dump(mode="json"))
            history.save_raw_response("standard_low_level", round_no, raw_low_level)
            history.save_parsed_response("standard_low_level", round_no, parsed_low_level.model_dump(mode="json"))

            main_error_batches.append((f"round_{round_no}_main_context", list(parsed_main.errorlist)))
            low_level_error_batches.append((f"round_{round_no}_local_chunk", list(parsed_low_level.errorlist)))

            combined_round = LLMRoundOutput(
                checklist=[] if is_final_round else parsed_main.checklist,
                errorlist=[*parsed_main.errorlist, *parsed_low_level.errorlist],
                notes=parsed_main.notes,
            )
            reconciled = reconcile_round(checklist, state_errorlist, combined_round)
            checklist = [] if is_final_round else reconciled.checklist
            state_errorlist = renumber_error_items(reconciled.errorlist)
            history.save_state(round_no, checklist, state_errorlist)
            self._report_agent_progress(current=round_no, total=total_rounds)

        final_errorlist = state_errorlist
        merge_mode = "local_only"
        merge_batches = [*main_error_batches, *low_level_error_batches]
        if merge_batches:
            self._report_reporting_stage()
            merge_start = perf_counter()
            main_fallback_errors = self._filter_errors_by_type(state_errorlist, MAIN_CONTEXT_ERROR_TYPES)
            local_fallback_errors = self._filter_errors_by_type(state_errorlist, LOCAL_CHUNK_ERROR_TYPES)
            (merged_main_errors, main_merge_calls, main_merge_mode), (
                merged_local_errors,
                local_merge_calls,
                local_merge_mode,
            ) = await asyncio.gather(
                self._merge_channel(
                    history=history,
                    stage="standard_merge_main",
                    merge_scope_label="context-aware main error channel (`*_main_context`)",
                    batches=main_error_batches,
                    fallback_errors=main_fallback_errors,
                    use_llm_merge=self.enable_merge_agent,
                ),
                self._merge_channel(
                    history=history,
                    stage="standard_merge_local",
                    merge_scope_label="local-error channel (`*_local_chunk`)",
                    batches=low_level_error_batches,
                    fallback_errors=local_fallback_errors,
                    use_llm_merge=self.enable_merge_agent,
                ),
            )
            llm_calls += main_merge_calls + local_merge_calls
            merge_mode = self._combine_merge_modes(main_merge_mode, local_merge_mode)
            final_errorlist = renumber_error_items([*merged_main_errors, *merged_local_errors])

            merge_elapsed_ms = max(1, int((perf_counter() - merge_start) * 1000))
            history.save_raw_response("standard_merge", 1, "PARALLEL_CHANNEL_LOCAL_COMBINE")
            history.save_parsed_response(
                "standard_merge",
                1,
                {
                    "main_context_errorlist": [item.model_dump(mode="json") for item in merged_main_errors],
                    "local_chunk_errorlist": [item.model_dump(mode="json") for item in merged_local_errors],
                    "errorlist": [item.model_dump(mode="json") for item in final_errorlist],
                    "round_reconciled_errorlist": [item.model_dump(mode="json") for item in state_errorlist],
                    "merge_mode": merge_mode,
                },
            )
            history.save_timing(
                stage="standard_merge_parallel",
                step=1,
                elapsed_ms=merge_elapsed_ms,
                details={
                    "all_batches": len(merge_batches),
                    "main_merge_candidate_count": sum(len(items) for _, items in main_error_batches),
                    "local_merge_candidate_count": sum(len(items) for _, items in low_level_error_batches),
                    "final_errors": len(final_errorlist),
                    "merge_mode": merge_mode,
                },
            )
            history.save_state("merge", checklist, final_errorlist)

        mode_elapsed_ms = max(1, int((perf_counter() - mode_start) * 1000))
        history.save_timing(stage="standard_total", step="all", elapsed_ms=mode_elapsed_ms)

        return ModeResult(
            mode=ModeName.STANDARD,
            checklist=checklist,
            errorlist=final_errorlist,
            stats=ModeStats(
                rounds=total_rounds,
                llm_calls=llm_calls,
                latency_ms=mode_elapsed_ms,
                input_chars=len(document.text),
                chunk_count=total_rounds,
                parser_backend=document.parser_backend,
            ),
            final_summary=(
                f"Standard mode finished with {len(final_errorlist)} confirmed errors "
                f"and {len(checklist)} pending checks after {total_rounds} chunk rounds"
                f"{self._merge_suffix(merge_mode)}."
            ),
            trace_refs=[str(history.paths.root.resolve())],
        )

    @staticmethod
    def _compact_checklist_json(items: list[CheckItem]) -> str:
        compact = [
            {
                "check_location": item.check_location,
                "check_explanation": item.check_explanation,
            }
            for item in items
        ]
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _round_errorlists_json(batches: list[tuple[str, list[ErrorItem]]]) -> str:
        payload: list[dict[str, object]] = []
        for source, items in batches:
            payload.append(
                {
                    "source": source,
                    "errorlist": [
                        {
                            "id": item.id,
                            "error_location": item.error_location,
                            "error_type": item.error_type.value,
                            "error_reason": item.error_reason,
                            "error_reasoning": item.error_reasoning,
                        }
                        for item in items
                    ],
                }
            )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _filter_errors_by_type(items: list[ErrorItem], allowed_types: frozenset[ErrorType]) -> list[ErrorItem]:
        return [item for item in items if item.error_type in allowed_types]

    @staticmethod
    def _flatten_error_batches(batches: list[tuple[str, list[ErrorItem]]]) -> list[ErrorItem]:
        flattened: list[ErrorItem] = []
        for _, items in batches:
            flattened.extend(items)
        return flattened

    @staticmethod
    def _combine_errorlists(main_errors: list[ErrorItem], low_level_errors: list[ErrorItem]) -> list[ErrorItem]:
        return renumber_error_items([*main_errors, *low_level_errors])

    async def _run_stage(self, *, messages, schema_model):  # noqa: ANN001
        llm_start = perf_counter()
        parsed, raw, _, _ = await self.llm_runner.run_contract(
            messages=messages,
            schema_model=schema_model,
            use_repair=True,
        )
        llm_elapsed_ms = max(1, int((perf_counter() - llm_start) * 1000))
        return parsed, raw, llm_elapsed_ms

    async def _run_merge_with_retry(self, *, messages):  # noqa: ANN001
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                return await self._run_stage(messages=messages, schema_model=ErrorMergeOutput)
            except (LLMRequestError, LLMOutputValidationError) as exc:
                last_error = exc
        if isinstance(last_error, (LLMRequestError, LLMOutputValidationError)):
            raise last_error
        raise LLMOutputValidationError("Merge agent failed without a captured error.")

    async def _merge_channel(
        self,
        *,
        history: HistoryStore,
        stage: str,
        merge_scope_label: str,
        batches: list[tuple[str, list[ErrorItem]]],
        fallback_errors: list[ErrorItem],
        use_llm_merge: bool,
    ) -> tuple[list[ErrorItem], int, str]:
        candidate_count = sum(len(items) for _, items in batches)
        if not use_llm_merge or candidate_count <= 1:
            history.save_raw_response(stage, 1, "CHANNEL_LOCAL_MERGE_SKIPPED")
            history.save_parsed_response(
                stage,
                1,
                {
                    "errorlist": [item.model_dump(mode="json") for item in fallback_errors],
                    "merge_candidate_count": candidate_count,
                    "notes": "merge_skipped_single_or_disabled",
                },
            )
            history.save_timing(
                stage=f"{stage}_local",
                step=1,
                elapsed_ms=1,
                details={
                    "merge_candidate_count": candidate_count,
                    "final_errors": len(fallback_errors),
                    "merge_mode": "local_only",
                },
            )
            return list(fallback_errors), 0, "local_only"

        merge_messages, merge_rendered = self.prompt_builder.build_messages(
            system_files=[
                "system/base_guardrails.md",
                "system/error_merge_json_contract.md",
            ],
            user_file="modes/standard_merge.md",
            variables={
                "merge_scope_label": merge_scope_label,
                "round_errorlists_json": self._round_errorlists_json(batches),
            },
        )
        history.save_prompt(stage, 1, merge_rendered)

        try:
            merged_output, merged_raw, merge_elapsed_ms = await self._run_merge_with_retry(messages=merge_messages)
            history.save_raw_response(stage, 1, merged_raw)
            merged_errors = list(merged_output.errorlist) or list(fallback_errors)
            merge_mode = "llm" if merged_output.errorlist else "llm_empty_fallback_local"
            history.save_parsed_response(
                stage,
                1,
                {
                    "errorlist": [item.model_dump(mode="json") for item in merged_errors],
                    "fallback_errorlist": [item.model_dump(mode="json") for item in fallback_errors],
                    "merge_candidate_count": candidate_count,
                    "notes": merged_output.notes,
                },
            )
            history.save_timing(
                stage=f"{stage}_llm",
                step=1,
                elapsed_ms=merge_elapsed_ms,
                details={
                    "merge_candidate_count": candidate_count,
                    "final_errors": len(merged_errors),
                    "merge_mode": merge_mode,
                },
            )
            return merged_errors, 1, merge_mode
        except (LLMRequestError, LLMOutputValidationError) as exc:
            merge_error = str(exc) or exc.__class__.__name__
            history.save_raw_response(stage, 1, f"MERGE_AGENT_FAILED\n{merge_error}")
            history.save_parsed_response(
                stage,
                1,
                {
                    "errorlist": [item.model_dump(mode="json") for item in fallback_errors],
                    "merge_candidate_count": candidate_count,
                    "notes": "fallback_to_round_reconcile",
                },
            )
            history.save_timing(
                stage=f"{stage}_llm",
                step=1,
                elapsed_ms=1,
                details={
                    "merge_candidate_count": candidate_count,
                    "final_errors": len(fallback_errors),
                    "merge_mode": "llm_fallback_local",
                    "error": merge_error[:500],
                },
            )
            return list(fallback_errors), 1, "llm_fallback_local"

    @staticmethod
    def _combine_merge_modes(*modes: str) -> str:
        if any("fallback" in mode for mode in modes):
            return "llm_fallback_local"
        if any(mode == "llm" for mode in modes):
            return "llm"
        return "local_only"

    @staticmethod
    def _merge_suffix(merge_mode: str) -> str:
        if merge_mode == "local_only":
            return " (local merge only)"
        if merge_mode == "llm_fallback_local":
            return " (merge agent failed, local merge used)"
        return ""

    def _report_agent_progress(self, *, current: int, total: int) -> None:
        emit_progress(
            self._progress_callback,
            stage=PROGRESS_STAGE_ANALYZING,
            label="Agent检测中",
            detail=chunk_progress_detail(current=current, total=total),
            current=current,
            total=total,
        )

    def _report_reporting_stage(self) -> None:
        emit_progress(
            self._progress_callback,
            stage=PROGRESS_STAGE_REPORTING,
            label="报告生成中",
            detail="正在合并结果并生成最终报告",
        )
