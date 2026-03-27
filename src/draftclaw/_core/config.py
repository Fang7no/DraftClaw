from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from draftclaw._resources import package_default_config_file
from draftclaw._core.enums import ModeName


class LLMConfig(BaseModel):
    api_key: str
    base_url: str
    model: str
    timeout_sec: float = 60.0
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 4096
    max_retries: int = 3
    retry_backoff_sec: float = 1.5
    use_json_schema: bool = True
    enable_cache: bool = True
    enable_merge_agent: bool = True


class IOConfig(BaseModel):
    working_dir: str = "output"
    runs_dir: str = "runs"
    output_filename_json: str = "mode_result.json"
    output_filename_md: str = "mode_result.md"
    output_filename_html: str = "mode_result.html"
    copy_input_file: bool = True


class ParserConfig(BaseModel):
    text_fast_path: bool = True
    cache_in_process: bool = True
    cache_on_disk: bool = True
    docling_page_chunk_size: int | None = Field(default=8, ge=1)
    pdf_parse_mode: Literal["fast", "accurate"] = "fast"
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_api_key: str = ""
    paddleocr_api_model: str = "PaddleOCR-VL-1.5"
    paddleocr_poll_interval_sec: float = Field(default=5.0, gt=0)
    paddleocr_api_timeout_sec: float = Field(default=120.0, gt=0)

    @field_validator("pdf_parse_mode", mode="before")
    @classmethod
    def _normalize_pdf_parse_mode(cls, value: object) -> str:
        return str(value or "fast").strip().lower() or "fast"


class StandardConfig(BaseModel):
    target_chunks: int = Field(default=0, ge=0, le=20)
    paragraph_separator_regex: str = r"\n\s*\n"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_file: str = "run.log"


class RunConfig(BaseModel):
    input_file: str = ""
    mode: ModeName | None = None
    run_name: str | None = None


class AppConfig(BaseModel):
    llm: LLMConfig
    run: RunConfig = Field(default_factory=RunConfig)
    io: IOConfig = Field(default_factory=IOConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    standard: StandardConfig = Field(default_factory=StandardConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def snapshot(self, *, redact_secrets: bool = True) -> dict[str, Any]:
        data = self.model_dump()
        if redact_secrets:
            data["llm"]["api_key"] = "***"
            data["parser"]["paddleocr_api_key"] = "***"
        return data


def _read_env(env_key: str) -> str:
    value = os.getenv(env_key)
    if value is None:
        value = os.getenv(f"\ufeff{env_key}")
    return "" if value is None else str(value).strip()


def _resolve_llm_string(
    llm_raw: Mapping[str, Any],
    *,
    field_name: str,
    legacy_env_field: str | None = None,
    default_env_key: str | None = None,
    fallback: str = "",
) -> str:
    direct_value = str(llm_raw.get(field_name, "")).strip()
    if direct_value:
        return direct_value

    if legacy_env_field is not None:
        legacy_env_key = str(llm_raw.get(legacy_env_field, "")).strip()
        if legacy_env_key:
            legacy_value = _read_env(legacy_env_key)
            if legacy_value:
                return legacy_value

    if default_env_key is not None:
        env_value = _read_env(default_env_key)
        if env_value:
            return env_value

    return fallback


def _resolve_llm_float(
    llm_raw: Mapping[str, Any],
    *,
    field_name: str,
    legacy_env_field: str | None = None,
    default_env_key: str | None = None,
    fallback: float,
) -> float:
    direct_value = llm_raw.get(field_name)
    if direct_value not in (None, ""):
        return float(direct_value)

    if legacy_env_field is not None:
        legacy_env_key = str(llm_raw.get(legacy_env_field, "")).strip()
        if legacy_env_key:
            legacy_value = _read_env(legacy_env_key)
            if legacy_value:
                return float(legacy_value)

    if default_env_key is not None:
        env_value = _read_env(default_env_key)
        if env_value:
            return float(env_value)

    return fallback


def build_config(raw: Mapping[str, Any] | None = None) -> AppConfig:
    raw_data = dict(raw or {})
    llm_raw = dict(raw_data.get("llm", {}))

    llm = LLMConfig(
        api_key=_resolve_llm_string(
            llm_raw,
            field_name="api_key",
            legacy_env_field="api_key_env",
            default_env_key="OPENAI_API_KEY",
            fallback="",
        ),
        base_url=_resolve_llm_string(
            llm_raw,
            field_name="base_url",
            legacy_env_field="base_url_env",
            default_env_key="OPENAI_BASE_URL",
            fallback="https://api.openai.com/v1",
        ),
        model=_resolve_llm_string(
            llm_raw,
            field_name="model",
            legacy_env_field="model_env",
            default_env_key="OPENAI_MODEL",
            fallback="gpt-4o-mini",
        ),
        timeout_sec=_resolve_llm_float(
            llm_raw,
            field_name="timeout_sec",
            legacy_env_field="timeout_sec_env",
            default_env_key="DRAFTCLAW_TIMEOUT_SEC",
            fallback=60.0,
        ),
        temperature=float(llm_raw.get("temperature", 0.0)),
        top_p=float(llm_raw.get("top_p", 1.0)),
        max_tokens=int(llm_raw.get("max_tokens", 4096)),
        max_retries=int(llm_raw.get("max_retries", 3)),
        retry_backoff_sec=float(llm_raw.get("retry_backoff_sec", 1.5)),
        use_json_schema=bool(llm_raw.get("use_json_schema", True)),
        enable_cache=bool(llm_raw.get("enable_cache", True)),
        enable_merge_agent=bool(llm_raw.get("enable_merge_agent", True)),
    )

    return AppConfig(
        llm=llm,
        run=RunConfig(**raw_data.get("run", {})),
        io=IOConfig(**raw_data.get("io", {})),
        parser=ParserConfig(**raw_data.get("parser", {})),
        standard=StandardConfig(**raw_data.get("standard", {})),
        logging=LoggingConfig(**raw_data.get("logging", {})),
    )


def load_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return build_config(raw)


def load_default_config() -> AppConfig:
    raw = yaml.safe_load(package_default_config_file().read_text(encoding="utf-8")) or {}
    return build_config(raw)
