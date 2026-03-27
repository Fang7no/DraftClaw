from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from draftclaw.app import DraftClawApp
from draftclaw._core.contracts import DocumentText, ModeResult
from draftclaw._core.enums import ModeName
from draftclaw._core.exceptions import DraftClawError, InputLoadError
from draftclaw.settings import DraftClawSettings, LLMOptions, ParserOptions


class ReviewOutcome(BaseModel):
    result: ModeResult
    run_dir: Path
    result_json: Path
    result_markdown: Path
    result_html: Path


class DocumentRun(BaseModel):
    document: DocumentText
    review: ReviewOutcome | None = None


class DraftClaw:
    """Simple synchronous facade for parsing and reviewing documents."""

    def __init__(
        self,
        *,
        settings: DraftClawSettings | None = None,
        llm: LLMOptions | None = None,
        config_path: str | Path | None = None,
        working_dir: str | Path | None = None,
    ) -> None:
        resolved_settings = self._resolve_settings(settings=settings, llm=llm)
        self._app = DraftClawApp(
            config_path=config_path,
            config=resolved_settings.to_app_config() if resolved_settings is not None else None,
            working_dir=working_dir,
        )

    @classmethod
    def create(
        cls,
        *,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        text_fast_path: bool = True,
        cache_in_process: bool = True,
        pdf_parse_mode: str = "fast",
        paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
        paddleocr_api_key: str = "",
        paddleocr_api_model: str = "PaddleOCR-VL-1.5",
        paddleocr_poll_interval_sec: float = 5.0,
        paddleocr_api_timeout_sec: float = 120.0,
        working_dir: str | Path | None = None,
    ) -> "DraftClaw":
        settings = DraftClawSettings(
            llm=LLMOptions(
                api_key=api_key,
                base_url=base_url,
                model=model,
            ),
            parser=ParserOptions(
                text_fast_path=text_fast_path,
                cache_in_process=cache_in_process,
                pdf_parse_mode=pdf_parse_mode,
                paddleocr_api_url=paddleocr_api_url,
                paddleocr_api_key=paddleocr_api_key,
                paddleocr_api_model=paddleocr_api_model,
                paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
                paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
            ),
        )
        return cls(settings=settings, working_dir=working_dir)

    @property
    def settings(self) -> DraftClawSettings:
        return DraftClawSettings.model_validate(self._app.config.model_dump(mode="python"))

    def parse(self, input_path: str | Path) -> DocumentText:
        validated_path = self._validate_input_path(input_path)
        return self._app.parse(validated_path)

    def parse_text(self, input_path: str | Path) -> str:
        return self.parse(input_path).text

    def parse_to_dict(self, input_path: str | Path) -> dict[str, Any]:
        return self.parse(input_path).model_dump(mode="json")

    def review(
        self,
        input_path: str | Path,
        *,
        mode: ModeName | str = ModeName.STANDARD,
        run_name: str | None = None,
    ) -> ReviewOutcome:
        validated_path = self._validate_input_path(input_path)
        self._validate_review_configuration()
        mode_name = self._normalize_mode(mode)
        result, run_dir = self._app.review_sync(
            input_path=str(validated_path),
            mode=mode_name,
            run_name=run_name,
        )
        return self._build_outcome(result, run_dir)

    async def review_async(
        self,
        input_path: str | Path,
        *,
        mode: ModeName | str = ModeName.STANDARD,
        run_name: str | None = None,
    ) -> ReviewOutcome:
        validated_path = self._validate_input_path(input_path)
        self._validate_review_configuration()
        mode_name = self._normalize_mode(mode)
        result, run_dir = await self._app.review(input_path=str(validated_path), mode=mode_name, run_name=run_name)
        return self._build_outcome(result, run_dir)

    def review_to_dict(
        self,
        input_path: str | Path,
        *,
        mode: ModeName | str = ModeName.STANDARD,
        run_name: str | None = None,
    ) -> dict[str, Any]:
        outcome = self.review(input_path, mode=mode, run_name=run_name)
        return {
            "run_dir": str(outcome.run_dir),
            "result_json": str(outcome.result_json),
            "result_markdown": str(outcome.result_markdown),
            "result_html": str(outcome.result_html),
            "result": outcome.result.model_dump(mode="json"),
        }

    def run(
        self,
        input_path: str | Path,
        *,
        review: bool = True,
        mode: ModeName | str = ModeName.STANDARD,
        run_name: str | None = None,
    ) -> DocumentRun:
        validated_path = self._validate_input_path(input_path)
        document = self._app.parse(validated_path)
        if not review:
            return DocumentRun(document=document)
        self._validate_review_configuration()
        mode_name = self._normalize_mode(mode)
        result, run_dir = self._app.review_sync(
            input_path=str(validated_path),
            mode=mode_name,
            run_name=run_name,
            document=document,
        )
        return DocumentRun(document=document, review=self._build_outcome(result, run_dir))

    def validate_result(self, result_path: str | Path) -> ModeResult:
        return self._app.validate_result(result_path)

    def capability_report(self) -> dict[str, dict[str, str | bool]]:
        return self._app.capability_report()

    @staticmethod
    def dump_result(result: ModeResult) -> str:
        return DraftClawApp.dump_result(result)

    def _validate_input_path(self, input_path: str | Path) -> Path:
        resolved = Path(input_path).expanduser()
        if not resolved.exists():
            raise InputLoadError(f"INPUT_FILE does not exist: {resolved}")
        if not resolved.is_file():
            raise InputLoadError(f"INPUT_FILE must be a file: {resolved}")

        suffix = resolved.suffix.lower().lstrip(".")
        if not suffix:
            raise InputLoadError("INPUT_FILE must include a file extension such as .pdf or .md.")

        report = self.capability_report()
        entry = report.get(suffix)
        if entry is None:
            supported = ", ".join(sorted(f".{item}" for item in report))
            raise InputLoadError(f"Unsupported input format '.{suffix}'. Supported formats: {supported}")
        if not bool(entry["supported"]):
            raise InputLoadError(f"Current environment cannot parse '.{suffix}' files: {entry['reason']}")

        return resolved

    def _validate_review_configuration(self) -> None:
        llm = self.settings.llm
        api_key = llm.api_key.strip()
        if not api_key or api_key in {"your_api_key", "***"}:
            raise DraftClawError("API key is not configured. Pass a real `api_key` before running review.")
        base_url = llm.base_url.strip()
        if not base_url:
            raise DraftClawError("BASE_URL cannot be empty.")
        if base_url.rstrip("/").endswith("/chat/completions"):
            raise DraftClawError("BASE_URL should be the API root, not the full /chat/completions endpoint.")
        if not base_url.startswith(("http://", "https://")):
            raise DraftClawError("BASE_URL must start with http:// or https://")
        if not llm.model.strip():
            raise DraftClawError("MODEL cannot be empty.")

    @staticmethod
    def _normalize_mode(mode: ModeName | str) -> ModeName:
        if isinstance(mode, ModeName):
            return mode
        try:
            return ModeName(str(mode).strip().lower())
        except ValueError as exc:
            raise DraftClawError("RUN_MODE only supports 'fast', 'standard', or 'deep'.") from exc

    @staticmethod
    def _resolve_settings(
        *,
        settings: DraftClawSettings | None,
        llm: LLMOptions | None,
    ) -> DraftClawSettings | None:
        if settings is None and llm is None:
            return None
        if settings is None:
            return DraftClawSettings(llm=llm)
        if llm is None:
            return settings
        return settings.model_copy(update={"llm": llm}, deep=True)

    def _build_outcome(self, result: ModeResult, run_dir: Path) -> ReviewOutcome:
        run_root = run_dir.resolve()
        config = self._app.config
        return ReviewOutcome(
            result=result,
            run_dir=run_root,
            result_json=run_root / "final" / config.io.output_filename_json,
            result_markdown=run_root / "final" / config.io.output_filename_md,
            result_html=run_root / "final" / config.io.output_filename_html,
        )


def create_client(
    *,
    settings: DraftClawSettings | None = None,
    llm: LLMOptions | None = None,
    config_path: str | Path | None = None,
    working_dir: str | Path | None = None,
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    text_fast_path: bool = True,
    cache_in_process: bool = True,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
    paddleocr_poll_interval_sec: float = 5.0,
    paddleocr_api_timeout_sec: float = 120.0,
) -> DraftClaw:
    if settings is not None or llm is not None or config_path is not None:
        return DraftClaw(settings=settings, llm=llm, config_path=config_path, working_dir=working_dir)
    return DraftClaw.create(
        api_key=api_key,
        base_url=base_url,
        model=model,
        text_fast_path=text_fast_path,
        cache_in_process=cache_in_process,
        pdf_parse_mode=pdf_parse_mode,
        paddleocr_api_url=paddleocr_api_url,
        paddleocr_api_key=paddleocr_api_key,
        paddleocr_api_model=paddleocr_api_model,
        paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
        paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
        working_dir=working_dir,
    )


def review_document(
    input_path: str | Path,
    *,
    mode: ModeName | str = ModeName.STANDARD,
    run_name: str | None = None,
    settings: DraftClawSettings | None = None,
    llm: LLMOptions | None = None,
    config_path: str | Path | None = None,
    working_dir: str | Path | None = None,
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    text_fast_path: bool = True,
    cache_in_process: bool = True,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
    paddleocr_poll_interval_sec: float = 5.0,
    paddleocr_api_timeout_sec: float = 120.0,
) -> ReviewOutcome:
    client = create_client(
        settings=settings,
        llm=llm,
        config_path=config_path,
        working_dir=working_dir,
        api_key=api_key,
        base_url=base_url,
        model=model,
        text_fast_path=text_fast_path,
        cache_in_process=cache_in_process,
        pdf_parse_mode=pdf_parse_mode,
        paddleocr_api_url=paddleocr_api_url,
        paddleocr_api_key=paddleocr_api_key,
        paddleocr_api_model=paddleocr_api_model,
        paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
        paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
    )
    return client.review(input_path, mode=mode, run_name=run_name)


def run_document(
    input_path: str | Path,
    *,
    review: bool = True,
    mode: ModeName | str = ModeName.STANDARD,
    run_name: str | None = None,
    settings: DraftClawSettings | None = None,
    llm: LLMOptions | None = None,
    config_path: str | Path | None = None,
    working_dir: str | Path | None = None,
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    text_fast_path: bool = True,
    cache_in_process: bool = True,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
    paddleocr_poll_interval_sec: float = 5.0,
    paddleocr_api_timeout_sec: float = 120.0,
) -> DocumentRun:
    client = create_client(
        settings=settings,
        llm=llm,
        config_path=config_path,
        working_dir=working_dir,
        api_key=api_key,
        base_url=base_url,
        model=model,
        text_fast_path=text_fast_path,
        cache_in_process=cache_in_process,
        pdf_parse_mode=pdf_parse_mode,
        paddleocr_api_url=paddleocr_api_url,
        paddleocr_api_key=paddleocr_api_key,
        paddleocr_api_model=paddleocr_api_model,
        paddleocr_poll_interval_sec=paddleocr_poll_interval_sec,
        paddleocr_api_timeout_sec=paddleocr_api_timeout_sec,
    )
    return client.run(input_path, review=review, mode=mode, run_name=run_name)
