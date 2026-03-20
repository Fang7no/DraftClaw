from __future__ import annotations

import logging
from datetime import datetime, timezone
from importlib.resources.abc import Traversable
from pathlib import Path
from time import perf_counter

from draftclaw._core.config import AppConfig
from draftclaw._core.contracts import DocumentText, InputMeta, ModeResult, RunRecord, RunTiming
from draftclaw._core.enums import ModeName
from draftclaw._core.logging import configure_logging
from draftclaw._history.store import HistoryStore
from draftclaw._history.trace import TraceLayout, create_run_id
from draftclaw._io.docling_parser import DoclingDocumentParser
from draftclaw._llm.cache import LLMCache
from draftclaw._llm.runner import LLMRunner
from draftclaw._modes.fast import FastMode
from draftclaw._modes.standard import StandardMode
from draftclaw._postprocess.finalize import prepare_mode_result
from draftclaw._prompts.builder import PromptBuilder
from draftclaw._resources import package_prompts_root
from draftclaw._runtime.paragraph_chunker import ParagraphChunker

LOGGER = logging.getLogger(__name__)
PROMPT_VERSION = "draftclaw-v1"


class ReviewService:
    def __init__(
        self,
        config: AppConfig,
        *,
        working_dir: str | Path | None = None,
        llm_override: dict[str, str] | None = None,
        prompts_root: str | Path | Traversable | None = None,
    ) -> None:
        self.config = config.model_copy(deep=True)
        configured_working_dir = self.config.io.working_dir.strip() if self.config.io.working_dir else ""
        runtime_working_dir = working_dir or configured_working_dir or Path.cwd()
        self.working_dir = Path(runtime_working_dir).resolve()

        if llm_override:
            api_key = llm_override.get("api_key", "").strip()
            base_url = llm_override.get("base_url", "").strip()
            model = llm_override.get("model", "").strip()
            if api_key:
                self.config.llm.api_key = api_key
            if base_url:
                self.config.llm.base_url = base_url
            if model:
                self.config.llm.model = model

        configure_logging(self.config.logging.level)

        self.input_parser = DoclingDocumentParser(
            text_fast_path=self.config.parser.text_fast_path,
            cache_in_process=self.config.parser.cache_in_process,
            cache_on_disk=self.config.parser.cache_on_disk,
            docling_page_chunk_size=self.config.parser.docling_page_chunk_size,
            working_dir=self.working_dir,
        )
        self.prompt_builder = PromptBuilder(prompts_root or package_prompts_root())
        self.chunker = ParagraphChunker(
            separator_regex=self.config.standard.paragraph_separator_regex,
            target_chunks=self.config.standard.target_chunks,
        )

        cache = LLMCache(self.working_dir / ".cache" / "llm") if self.config.llm.enable_cache else None
        self.llm_runner = LLMRunner(self.config.llm, cache=cache)
        self.fast_mode = FastMode(
            self.prompt_builder,
            self.llm_runner,
            self.chunker,
            enable_merge_agent=self.config.llm.enable_merge_agent,
        )
        self.standard_mode = StandardMode(
            chunker=self.chunker,
            prompt_builder=self.prompt_builder,
            llm_runner=self.llm_runner,
            enable_merge_agent=self.config.llm.enable_merge_agent,
        )

    async def review(
        self,
        *,
        input_path: str,
        mode: ModeName,
        run_name: str | None = None,
        document: DocumentText | None = None,
    ) -> tuple[ModeResult, Path]:
        review_start = perf_counter()

        runs_root = self._resolve_runtime_path(self.config.io.runs_dir)
        layout = TraceLayout(runs_root)
        run_id = create_run_id(run_name)
        run_paths = layout.create(run_id)
        history = HistoryStore(run_paths)
        run_log_path = run_paths.logs / self.config.logging.log_file
        self._append_run_log(run_log_path, f"Run start | mode={mode.value} | input={input_path}")

        document = document or self.input_parser.parse(input_path)
        history.save_document_manifest(document)
        if self.config.io.copy_input_file:
            history.save_input_file(document.path, Path(document.path).suffix)
        history.save_preprocess_text(document.text)

        run_record = RunRecord(
            run_id=run_id,
            mode=mode,
            input_meta=InputMeta(
                input_path=document.path,
                input_type=document.input_type,
                file_size=document.file_size,
                sha256=document.sha256,
                parser_backend=document.parser_backend,
            ),
            config_snapshot=self.config.snapshot(),
            prompt_version=PROMPT_VERSION,
            timing=RunTiming(started_at=datetime.now(timezone.utc)),
        )

        async with self.llm_runner.session():
            if mode == ModeName.FAST:
                result = await self.fast_mode.run(document=document, history=history)
            elif mode == ModeName.STANDARD:
                result = await self.standard_mode.run(document=document, history=history)
            else:  # pragma: no cover
                raise ValueError(f"Unsupported mode: {mode}")
        result = prepare_mode_result(result)

        final_json, final_md, final_html = history.save_final_result(
            result,
            document,
            json_name=self.config.io.output_filename_json,
            md_name=self.config.io.output_filename_md,
            html_name=self.config.io.output_filename_html,
        )

        run_record.llm_calls = result.stats.llm_calls
        run_record.artifacts = {
            "final_json": str(final_json.resolve()),
            "final_md": str(final_md.resolve()),
            "final_html": str(final_html.resolve()),
            "run_root": str(run_paths.root.resolve()),
        }
        run_record.timing.finished_at = datetime.now(timezone.utc)
        run_record.timing.duration_ms = max(1, int((perf_counter() - review_start) * 1000))
        history.save_run_record(run_record)
        history.save_timing(
            stage="review_total",
            step="all",
            elapsed_ms=run_record.timing.duration_ms,
            details={
                "mode_latency_ms": result.stats.latency_ms,
                "parser_backend": document.parser_backend,
            },
        )
        self._append_run_log(
            run_log_path,
            (
                f"Run complete | llm_calls={result.stats.llm_calls} | "
                f"errors={len(result.errorlist)} | checks={len(result.checklist)} | "
                f"duration_ms={run_record.timing.duration_ms}"
            ),
        )

        LOGGER.info("Run complete: %s", run_paths.root)
        return result, run_paths.root

    def validate_result(self, result_path: str | Path) -> ModeResult:
        return ModeResult.model_validate_json(Path(result_path).read_text(encoding="utf-8"))

    def capability_report(self) -> dict[str, dict[str, str | bool]]:
        return self.input_parser.capability_report()

    def _resolve_runtime_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return (self.working_dir / path).resolve()

    @staticmethod
    def _append_run_log(path: Path, message: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} | {message}\n")
