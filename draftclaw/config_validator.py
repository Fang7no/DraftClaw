"""
Runtime configuration validation with cached success fingerprints.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

import requests

import config
from agents.llm_utils import ChatCompletionClient


VALIDATION_CACHE_PATH = config.WEB_TASKS_DIR / "config_validation_cache.json"
VALIDATION_LOG_AGENT = "ConfigValidator"


class ConfigValidationError(RuntimeError):
    """Raised when a required runtime configuration check fails."""


def _emit_log(
    log_callback: Callable[[str, str, str, Dict[str, Any]], None] | None,
    *,
    stage: str,
    message: str,
    data: Dict[str, Any] | None = None,
) -> None:
    if callable(log_callback):
        log_callback(VALIDATION_LOG_AGENT, stage, message, data or {})


def _normalized_validation_payload(runtime_config: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "mineru_api_url": str(runtime_config.get("mineru_api_url", "") or "").strip(),
        "mineru_api_key": str(runtime_config.get("mineru_api_key", "") or "").strip(),
        "review_api_url": str(runtime_config.get("review_api_url", "") or "").strip(),
        "review_api_key": str(runtime_config.get("review_api_key", "") or "").strip(),
        "review_model": str(runtime_config.get("review_model", "") or "").strip(),
        "recheck_llm_api_url": str(runtime_config.get("recheck_llm_api_url", "") or "").strip(),
        "recheck_llm_api_key": str(runtime_config.get("recheck_llm_api_key", "") or "").strip(),
        "recheck_llm_model": str(runtime_config.get("recheck_llm_model", "") or "").strip(),
        "recheck_vlm_api_url": str(runtime_config.get("recheck_vlm_api_url", "") or "").strip(),
        "recheck_vlm_api_key": str(runtime_config.get("recheck_vlm_api_key", "") or "").strip(),
        "recheck_vlm_model": str(runtime_config.get("recheck_vlm_model", "") or "").strip(),
        "search_engine": str(runtime_config.get("search_engine", "") or "").strip().lower(),
        "serper_api_key": str(runtime_config.get("serper_api_key", "") or "").strip(),
    }
    return payload


def build_config_validation_fingerprint(runtime_config: Dict[str, Any]) -> str:
    normalized_payload = _normalized_validation_payload(runtime_config)
    serialized = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _read_validation_cache(cache_path: Path = VALIDATION_CACHE_PATH) -> Dict[str, Any]:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_validation_cache(payload: Dict[str, Any], cache_path: Path = VALIDATION_CACHE_PATH) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_configured(api_url: str, api_key: str, model: str) -> bool:
    return bool(str(api_url).strip() and str(api_key).strip() and str(model).strip())


def _is_partially_configured(*values: str) -> bool:
    present = [bool(str(value or "").strip()) for value in values]
    return any(present) and not all(present)


def _require_non_empty(label: str, value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ConfigValidationError(f"{label} is required.")
    return normalized


def _validate_optional_model_config(label: str, api_url: str, api_key: str, model: str) -> bool:
    if _is_partially_configured(api_url, api_key, model):
        raise ConfigValidationError(
            f"{label} configuration is incomplete. Fill URL, API Key, and Model together, or leave all blank."
        )
    return _is_configured(api_url, api_key, model)


def _validate_mineru_connection(api_url: str, api_key: str) -> None:
    api_url = _require_non_empty("MinerU API URL", api_url)
    api_key = _require_non_empty("MinerU API Key", api_key)
    url = f"{api_url.rstrip('/')}/file-urls/batch"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "files": [{"name": "config-validation.pdf", "data_id": "config-validation.pdf"}],
        "model_version": "vlm",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("code") != 0:
        message = body.get("msg") if isinstance(body, dict) else "Unexpected MinerU response"
        raise ConfigValidationError(f"MinerU validation failed: {message}")


def _validate_chat_model(label: str, api_url: str, api_key: str, model: str) -> None:
    api_url = _require_non_empty(f"{label} URL", api_url)
    api_key = _require_non_empty(f"{label} API Key", api_key)
    model = _require_non_empty(f"{label} Model", model)
    client = ChatCompletionClient(
        api_url=api_url,
        api_key=api_key,
        model=model,
        default_timeout=45,
        max_retries=1,
    )
    result = client.complete(
        [
            {"role": "system", "content": "You are validating API connectivity."},
            {"role": "user", "content": "Reply with OK only."},
        ],
        temperature=0,
        max_tokens=16,
        response_format=None,
        stream=False,
    )
    if "ok" not in str(result.content or "").strip().lower():
        raise ConfigValidationError(f"{label} validation failed: unexpected model response.")


def _validate_serper(api_key: str) -> None:
    if not str(api_key or "").strip():
        raise ConfigValidationError("Serper API Key is required when Search Engine = Serper.")
    response = requests.post(
        "https://google.serper.dev/search",
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        json={"q": "DraftClaw configuration validation", "num": 1},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ConfigValidationError("Serper validation failed: unexpected response.")
    if body.get("message"):
        raise ConfigValidationError(f"Serper validation failed: {body['message']}")


def validate_runtime_configuration(
    *,
    runtime_config: Dict[str, Any] | None = None,
    log_callback: Callable[[str, str, str, Dict[str, Any]], None] | None = None,
    force: bool = False,
    cache_path: Path = VALIDATION_CACHE_PATH,
) -> Dict[str, Any]:
    runtime_values = runtime_config or config.get_runtime_config(mask_secrets=False)
    payload = _normalized_validation_payload(runtime_values)
    fingerprint = build_config_validation_fingerprint(runtime_values)
    cache = _read_validation_cache(cache_path)
    cached_fingerprint = str(cache.get("last_success_fingerprint", "") or "").strip()
    cached_validated_at = str(cache.get("validated_at", "") or "").strip()

    _emit_log(
        log_callback,
        stage="config_validation_start",
        message="Starting runtime configuration validation",
        data={"fingerprint": fingerprint[:12]},
    )

    if not force and cached_fingerprint and cached_fingerprint == fingerprint:
        _emit_log(
            log_callback,
            stage="config_validation_cache_hit",
            message="Configuration unchanged since last successful validation; skipped.",
            data={"fingerprint": fingerprint[:12], "validated_at": cached_validated_at},
        )
        return {
            "ok": True,
            "cached": True,
            "fingerprint": fingerprint,
            "validated_at": cached_validated_at,
        }

    try:
        _emit_log(
            log_callback,
            stage="config_validation_step",
            message="Validating MinerU parser configuration",
            data={"target": "mineru"},
        )
        _validate_mineru_connection(payload["mineru_api_url"], payload["mineru_api_key"])

        _emit_log(
            log_callback,
            stage="config_validation_step",
            message="Validating Review Model configuration",
            data={"target": "review_model", "model": payload["review_model"]},
        )
        _validate_chat_model(
            "Review Model",
            payload["review_api_url"],
            payload["review_api_key"],
            payload["review_model"],
        )

        if _validate_optional_model_config(
            "Recheck LLM",
            payload["recheck_llm_api_url"],
            payload["recheck_llm_api_key"],
            payload["recheck_llm_model"],
        ):
            _emit_log(
                log_callback,
                stage="config_validation_step",
                message="Validating Recheck LLM configuration",
                data={"target": "recheck_llm", "model": payload["recheck_llm_model"]},
            )
            _validate_chat_model(
                "Recheck LLM",
                payload["recheck_llm_api_url"],
                payload["recheck_llm_api_key"],
                payload["recheck_llm_model"],
            )

        if _validate_optional_model_config(
            "Recheck VLM",
            payload["recheck_vlm_api_url"],
            payload["recheck_vlm_api_key"],
            payload["recheck_vlm_model"],
        ):
            _emit_log(
                log_callback,
                stage="config_validation_step",
                message="Validating Recheck VLM configuration",
                data={"target": "recheck_vlm", "model": payload["recheck_vlm_model"]},
            )
            _validate_chat_model(
                "Recheck VLM",
                payload["recheck_vlm_api_url"],
                payload["recheck_vlm_api_key"],
                payload["recheck_vlm_model"],
            )

        if payload["search_engine"] == "serper":
            _emit_log(
                log_callback,
                stage="config_validation_step",
                message="Validating Serper configuration",
                data={"target": "serper"},
            )
            _validate_serper(payload["serper_api_key"])
    except Exception as exc:
        _emit_log(
            log_callback,
            stage="config_validation_error",
            message=f"Runtime configuration validation failed: {exc}",
            data={"fingerprint": fingerprint[:12]},
        )
        if isinstance(exc, ConfigValidationError):
            raise
        raise ConfigValidationError(str(exc)) from exc

    validated_at = datetime.now().isoformat()
    _write_validation_cache(
        {
            "last_success_fingerprint": fingerprint,
            "validated_at": validated_at,
        },
        cache_path,
    )
    _emit_log(
        log_callback,
        stage="config_validation_success",
        message="Runtime configuration validated successfully",
        data={"fingerprint": fingerprint[:12], "validated_at": validated_at},
    )
    return {
        "ok": True,
        "cached": False,
        "fingerprint": fingerprint,
        "validated_at": validated_at,
    }
