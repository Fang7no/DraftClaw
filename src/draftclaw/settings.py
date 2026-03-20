from __future__ import annotations

import os

from draftclaw._core.config import AppConfig, IOConfig, LLMConfig, LoggingConfig, ParserConfig, StandardConfig, load_default_config


class LLMOptions(LLMConfig):
    @classmethod
    def from_env(
        cls,
        *,
        api_key_env: str = "OPENAI_API_KEY",
        base_url_env: str = "OPENAI_BASE_URL",
        model_env: str = "OPENAI_MODEL",
        timeout_env: str = "DRAFTCLAW_TIMEOUT_SEC",
    ) -> "LLMOptions":
        api_key = os.getenv(api_key_env, "").strip()
        if not api_key:
            raise ValueError(f"Missing environment variable: {api_key_env}")

        base_url = os.getenv(base_url_env, "https://api.openai.com/v1").strip() or "https://api.openai.com/v1"
        model = os.getenv(model_env, "gpt-4o-mini").strip() or "gpt-4o-mini"
        timeout_raw = os.getenv(timeout_env, "60").strip() or "60"

        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_sec=float(timeout_raw),
        )


class IOOptions(IOConfig):
    pass


class ParserOptions(ParserConfig):
    pass


class StandardOptions(StandardConfig):
    pass


class LoggingOptions(LoggingConfig):
    pass


class DraftClawSettings(AppConfig):
    @classmethod
    def default(cls) -> "DraftClawSettings":
        return cls.model_validate(load_default_config().model_dump(mode="python"))

    @classmethod
    def from_env(cls) -> "DraftClawSettings":
        return cls(llm=LLMOptions.from_env())

    def to_app_config(self) -> AppConfig:
        return AppConfig.model_validate(self.model_dump(mode="python"))
