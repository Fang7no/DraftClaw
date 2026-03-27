from __future__ import annotations

import asyncio
import json
from time import perf_counter

from draftclaw._core.contracts import DeepPlanOutput, DocumentText, ErrorMergeOutput, LLMRoundOutput, ModeResult, ModeStats
from draftclaw._core.enums import ModeName
from draftclaw._history.store import HistoryStore
from draftclaw._postprocess.dedup import renumber_error_items
from draftclaw._postprocess.reconcile import reconcile_round
from draftclaw._modes.standard import LOCAL_CHUNK_ERROR_TYPES, MAIN_CONTEXT_ERROR_TYPES, StandardMode
from draftclaw._prompts.builder import PromptBuilder
from draftclaw._runtime.paragraph_chunker import ParagraphChunker


class DeepMode(StandardMode):
    def __init__(
        self,
        *,
        chunker: ParagraphChunker,
        prompt_builder: PromptBuilder,
        llm_runner,
        enable_merge_agent: bool = True,
        progress_callback=None,
    ) -> None:
        super().__init__(
            chunker=chunker,
            prompt_builder=prompt_builder,
            llm_runner=llm_runner,
            enable_merge_agent=enable_merge_agent,
            progress_callback=progress_callback,
        )

    async def run(self, *, document: DocumentText, history: HistoryStore) -> ModeResult:
        mode_start = perf_counter()

        chunks, infos = self.chunker.split(document.text)
        history.save_chunks(chunks, infos)
        total_rounds = len(chunks)
        self._report_agent_progress(current=0, total=total_rounds)

        checklist = []
        state_errorlist = []
        main_error_batches = []
        low_level_error_batches = []
        llm_calls = 0

        for round_no in range(1, total_rounds + 1):
            current_chunk = chunks[round_no - 1]
            history_text = "\n\n".join(chunks[: round_no - 1])
            is_final_round = round_no == total_rounds

            plan_messages, plan_rendered = self.prompt_builder.build_messages(
                system_files=[
                    "system/base_guardrails.md",
                    "system/json_only_contract.md",
                ],
                user_file="modes/deep_plan_round.md",
                variables={
                    "round_no": round_no,
                    "total_rounds": total_rounds,
                    "is_final_round": is_final_round,
                    "current_chunk_text": current_chunk,
                    "history_text": history_text,
                    "checklist_json": self._compact_checklist_json(checklist),
                },
            )
            history.save_prompt("deep_plan", round_no, plan_rendered)
            parsed_plan, raw_plan, plan_elapsed_ms = await self._run_stage(
                messages=plan_messages,
                schema_model=DeepPlanOutput,
            )
            llm_calls += 1
            history.save_timing(
                stage="deep_plan_llm",
                step=round_no,
                elapsed_ms=plan_elapsed_ms,
                details={
                    "input_chars": len(current_chunk),
                    "history_chars": len(history_text),
                    "check_items_in": len(checklist),
                    "planned_items": len(parsed_plan.plan),
                },
            )
            history.save_raw_response("deep_plan", round_no, raw_plan)
            history.save_parsed_response("deep_plan", round_no, parsed_plan.model_dump(mode="json"))

            execute_messages, execute_rendered = self.prompt_builder.build_messages(
                system_files=[
                    "system/base_guardrails.md",
                    "system/json_only_contract.md",
                ],
                user_file="modes/deep_execute_round.md",
                variables={
                    "round_no": round_no,
                    "total_rounds": total_rounds,
                    "is_final_round": is_final_round,
                    "current_chunk_text": current_chunk,
                    "history_text": history_text,
                    "checklist_json": self._compact_checklist_json(checklist),
                    "plan_json": self._compact_plan_json(parsed_plan),
                },
            )
            history.save_prompt("deep_execute", round_no, execute_rendered)
            parsed_execute, raw_execute, execute_elapsed_ms = await self._run_stage(
                messages=execute_messages,
                schema_model=LLMRoundOutput,
            )
            llm_calls += 1
            history.save_timing(
                stage="deep_execute_llm",
                step=round_no,
                elapsed_ms=execute_elapsed_ms,
                details={
                    "input_chars": len(current_chunk),
                    "history_chars": len(history_text),
                    "planned_items": len(parsed_plan.plan),
                    "new_errors": len(parsed_execute.errorlist),
                    "new_checks": len(parsed_execute.checklist),
                },
            )
            history.save_raw_response("deep_execute", round_no, raw_execute)
            history.save_parsed_response("deep_execute", round_no, parsed_execute.model_dump(mode="json"))

            validate_messages, validate_rendered = self.prompt_builder.build_messages(
                system_files=[
                    "system/base_guardrails.md",
                    "system/json_only_contract.md",
                ],
                user_file="modes/deep_validate_round.md",
                variables={
                    "round_no": round_no,
                    "total_rounds": total_rounds,
                    "is_final_round": is_final_round,
                    "current_chunk_text": current_chunk,
                    "history_text": history_text,
                    "checklist_json": self._compact_checklist_json(checklist),
                    "plan_json": self._compact_plan_json(parsed_plan),
                    "proposed_output_json": self._compact_round_output_json(parsed_execute),
                },
            )
            history.save_prompt("deep_validate", round_no, validate_rendered)
            parsed_main, raw_main, validate_elapsed_ms = await self._run_stage(
                messages=validate_messages,
                schema_model=LLMRoundOutput,
            )
            llm_calls += 1
            history.save_timing(
                stage="deep_validate_llm",
                step=round_no,
                elapsed_ms=validate_elapsed_ms,
                details={
                    "input_chars": len(current_chunk),
                    "history_chars": len(history_text),
                    "planned_items": len(parsed_plan.plan),
                    "proposed_errors": len(parsed_execute.errorlist),
                    "proposed_checks": len(parsed_execute.checklist),
                    "final_errors": len(parsed_main.errorlist),
                    "final_checks": len(parsed_main.checklist),
                },
            )
            history.save_raw_response("deep_validate", round_no, raw_main)
            history.save_parsed_response("deep_validate", round_no, parsed_main.model_dump(mode="json"))

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
            history.save_prompt("deep_low_level", round_no, low_level_rendered)
            parsed_low_level, raw_low_level, low_level_elapsed_ms = await self._run_stage(
                messages=low_level_messages,
                schema_model=ErrorMergeOutput,
            )
            llm_calls += 1
            history.save_timing(
                stage="deep_low_level_llm",
                step=round_no,
                elapsed_ms=low_level_elapsed_ms,
                details={
                    "input_chars": len(current_chunk),
                    "new_errors": len(parsed_low_level.errorlist),
                },
            )
            history.save_raw_response("deep_low_level", round_no, raw_low_level)
            history.save_parsed_response("deep_low_level", round_no, parsed_low_level.model_dump(mode="json"))

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
            ) = await self._run_parallel_channel_merge(
                history=history,
                main_error_batches=main_error_batches,
                low_level_error_batches=low_level_error_batches,
                main_fallback_errors=main_fallback_errors,
                local_fallback_errors=local_fallback_errors,
            )
            llm_calls += main_merge_calls + local_merge_calls
            merge_mode = self._combine_merge_modes(main_merge_mode, local_merge_mode)
            final_errorlist = renumber_error_items([*merged_main_errors, *merged_local_errors])

            merge_elapsed_ms = max(1, int((perf_counter() - merge_start) * 1000))
            history.save_raw_response("deep_merge", 1, "PARALLEL_CHANNEL_LOCAL_COMBINE")
            history.save_parsed_response(
                "deep_merge",
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
                stage="deep_merge_parallel",
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
        history.save_timing(stage="deep_total", step="all", elapsed_ms=mode_elapsed_ms)

        return ModeResult(
            mode=ModeName.DEEP,
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
                f"Deep mode finished with {len(final_errorlist)} confirmed errors "
                f"and {len(checklist)} pending checks after {total_rounds} chunk rounds"
                f"{self._merge_suffix(merge_mode)}."
            ),
            trace_refs=[str(history.paths.root.resolve())],
        )

    async def _run_parallel_channel_merge(
        self,
        *,
        history: HistoryStore,
        main_error_batches,
        low_level_error_batches,
        main_fallback_errors,
        local_fallback_errors,
    ):
        return await asyncio.gather(
            self._merge_channel(
                history=history,
                stage="deep_merge_main",
                merge_scope_label="context-aware main error channel (`*_main_context`)",
                batches=main_error_batches,
                fallback_errors=main_fallback_errors,
                use_llm_merge=self.enable_merge_agent,
            ),
            self._merge_channel(
                history=history,
                stage="deep_merge_local",
                merge_scope_label="local-error channel (`*_local_chunk`)",
                batches=low_level_error_batches,
                fallback_errors=local_fallback_errors,
                use_llm_merge=self.enable_merge_agent,
            ),
        )

    @staticmethod
    def _compact_plan_json(plan: DeepPlanOutput) -> str:
        return json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _compact_round_output_json(output: LLMRoundOutput) -> str:
        return json.dumps(output.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
