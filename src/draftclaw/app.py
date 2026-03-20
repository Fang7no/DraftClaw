from __future__ import annotations

import asyncio
import json
from pathlib import Path

from draftclaw._core.config import AppConfig, load_config, load_default_config
from draftclaw._core.contracts import DocumentText, ModeResult
from draftclaw._core.enums import ModeName
from draftclaw._runtime.service import ReviewService


class DraftClawApp:
    def __init__(
        self,
        config_path: str | Path | None = None,
        config: AppConfig | None = None,
        llm_override: dict[str, str] | None = None,
        working_dir: str | Path | None = None,
    ) -> None:
        resolved_config = config.model_copy(deep=True) if config is not None else self._load_config(config_path)
        self._service = ReviewService(resolved_config, working_dir=working_dir, llm_override=llm_override)

    async def review(
        self,
        *,
        input_path: str,
        mode: ModeName,
        run_name: str | None = None,
        document: DocumentText | None = None,
    ) -> tuple[ModeResult, Path]:
        return await self._service.review(input_path=input_path, mode=mode, run_name=run_name, document=document)

    def review_sync(
        self,
        *,
        input_path: str,
        mode: ModeName,
        run_name: str | None = None,
        document: DocumentText | None = None,
    ) -> tuple[ModeResult, Path]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.review(input_path=input_path, mode=mode, run_name=run_name, document=document))
        raise RuntimeError("A running event loop was detected. Use `await DraftClawApp.review(...)` instead.")

    def parse(self, input_path: str | Path) -> DocumentText:
        return self._service.input_parser.parse(input_path)

    def parse_text(self, input_path: str | Path) -> str:
        return self.parse(input_path).text

    def validate_result(self, result_path: str | Path) -> ModeResult:
        return self._service.validate_result(result_path)

    def capability_report(self) -> dict[str, dict[str, str | bool]]:
        return self._service.capability_report()

    @property
    def config(self) -> AppConfig:
        return self._service.config.model_copy(deep=True)

    @staticmethod
    def dump_result(result: ModeResult) -> str:
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)

    @staticmethod
    def _load_config(config_path: str | Path | None) -> AppConfig:
        if config_path is None:
            return load_default_config()
        return load_config(config_path)
