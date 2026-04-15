"""
Project configuration with runtime reload support.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict

from env_utils import PACKAGE_DIR, load_runtime_dotenv, resolve_env_path


BASE_DIR = PACKAGE_DIR
ENV_PATH = resolve_env_path()
PROMPTS_DIR = BASE_DIR / "prompts"
RUNTIME_DIR = BASE_DIR / "runtime"
LEGACY_CACHE_DIR = BASE_DIR / "cache"
LEGACY_LOGS_DIR = BASE_DIR / "logs"
LEGACY_WEB_TASKS_DIR = BASE_DIR / "web_tasks"
RUNTIME_CACHE_DIR = RUNTIME_DIR / "cache"
RUNTIME_LOGS_DIR = RUNTIME_DIR / "logs"
RUNTIME_WEB_TASKS_DIR = RUNTIME_DIR / "web_tasks"

_RUNTIME_DIR_PAIRS = (
    (LEGACY_CACHE_DIR, RUNTIME_CACHE_DIR),
    (LEGACY_LOGS_DIR, RUNTIME_LOGS_DIR),
    (LEGACY_WEB_TASKS_DIR, RUNTIME_WEB_TASKS_DIR),
)

CONFIG_FIELD_MAP = {
    "mineru_api_url": "MINERU_API_URL",
    "mineru_api_key": "MINERU_API_KEY",
    "review_api_url": "REVIEW_API_URL",
    "review_api_key": "REVIEW_API_KEY",
    "review_model": "REVIEW_MODEL",
    "recheck_llm_api_url": "RECHECK_LLM_API_URL",
    "recheck_llm_api_key": "RECHECK_LLM_API_KEY",
    "recheck_llm_model": "RECHECK_LLM_MODEL",
    "recheck_vlm_api_url": "RECHECK_VLM_API_URL",
    "recheck_vlm_api_key": "RECHECK_VLM_API_KEY",
    "recheck_vlm_model": "RECHECK_VLM_MODEL",
    "llm_request_min_interval_seconds": "LLM_REQUEST_MIN_INTERVAL_SECONDS",
    "report_language": "REPORT_LANGUAGE",
    "search_engine": "SEARCH_ENGINE",
    "serper_api_key": "SERPER_API_KEY",
    "review_parallelism": "REVIEW_PARALLELISM",
}

SECRET_FIELDS = {
    "mineru_api_key",
    "review_api_key",
    "recheck_llm_api_key",
    "recheck_vlm_api_key",
    "qwen_api_key",
    "serper_api_key",
}

LEGACY_CONFIG_ALIASES = {
    "qwen_api_url": "review_api_url",
    "qwen_api_key": "review_api_key",
    "qwen_model": "review_model",
    "qwen_review_model": "review_model",
    "vision_api_url": "recheck_vlm_api_url",
    "vision_api_key": "recheck_vlm_api_key",
    "vision_model": "recheck_vlm_model",
    "qwen_vision_model": "recheck_vlm_model",
    "recheck_api_url": "recheck_llm_api_url",
    "recheck_api_key": "recheck_llm_api_key",
    "recheck_model": "recheck_llm_model",
    "qwen_recheck_model": "recheck_llm_model",
}

REVIEW_MODE_FEATURES = {
    "fast": {
        "vision_enabled": False,
        "search_enabled": False,
    },
    "standard": {
        "vision_enabled": True,
        "search_enabled": False,
    },
    "deep": {
        "vision_enabled": True,
        "search_enabled": True,
    },
}


def normalize_review_mode(value: str) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in REVIEW_MODE_FEATURES else "standard"


def resolve_review_mode_features(mode: str) -> Dict[str, bool]:
    normalized_mode = normalize_review_mode(mode)
    features = REVIEW_MODE_FEATURES[normalized_mode]
    return {
        "vision_enabled": bool(features["vision_enabled"]),
        "search_enabled": bool(features["search_enabled"]),
    }


def _merge_directory(source: Path, target: Path) -> bool:
    """Move legacy runtime contents into the canonical runtime directory."""
    if not source.exists() or source == target:
        return True

    if not target.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            return True
        except OSError:
            return False

    target.mkdir(parents=True, exist_ok=True)
    migrated = True
    for child in source.iterdir():
        destination = target / child.name
        if destination.exists():
            if child.is_dir() and destination.is_dir():
                migrated = _merge_directory(child, destination) and migrated
            continue
        try:
            shutil.move(str(child), str(destination))
        except OSError:
            migrated = False

    try:
        source.rmdir()
    except OSError:
        migrated = False
    return migrated


def _choose_active_runtime_dir(legacy_dir: Path, runtime_dir: Path) -> Path:
    if runtime_dir.exists():
        try:
            next(runtime_dir.iterdir())
            return runtime_dir
        except StopIteration:
            pass
    if legacy_dir.exists():
        return legacy_dir
    return runtime_dir


def ensure_runtime_layout() -> None:
    """Create canonical runtime directories and migrate legacy ones when present."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for legacy_dir, runtime_dir in _RUNTIME_DIR_PAIRS:
        if legacy_dir.exists():
            _merge_directory(legacy_dir, runtime_dir)
        else:
            runtime_dir.mkdir(parents=True, exist_ok=True)


def normalize_runtime_path(value: str) -> str:
    """Rewrite legacy runtime paths into the canonical runtime layout."""
    text = str(value or "")
    if not text:
        return text

    normalized_text = text.replace("/", "\\")
    normalized_lower = normalized_text.lower()
    for legacy_dir, runtime_dir in (
        (LEGACY_CACHE_DIR, CACHE_DIR),
        (LEGACY_LOGS_DIR, LOGS_DIR),
        (LEGACY_WEB_TASKS_DIR, WEB_TASKS_DIR),
    ):
        legacy_text = str(legacy_dir).replace("/", "\\")
        legacy_lower = legacy_text.lower()
        if normalized_lower == legacy_lower:
            return str(runtime_dir)
        prefix = f"{legacy_lower}\\"
        if normalized_lower.startswith(prefix):
            suffix = normalized_text[len(legacy_text):].lstrip("\\/")
            return str(runtime_dir / Path(suffix)) if suffix else str(runtime_dir)
    return text


def normalize_runtime_value(value: Any) -> Any:
    """Recursively normalize runtime paths inside task/result payloads."""
    if isinstance(value, dict):
        return {key: normalize_runtime_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [normalize_runtime_value(item) for item in value]
    if isinstance(value, str):
        return normalize_runtime_path(value)
    return value


ensure_runtime_layout()
CACHE_DIR = _choose_active_runtime_dir(LEGACY_CACHE_DIR, RUNTIME_CACHE_DIR)
LOGS_DIR = _choose_active_runtime_dir(LEGACY_LOGS_DIR, RUNTIME_LOGS_DIR)
WEB_TASKS_DIR = _choose_active_runtime_dir(LEGACY_WEB_TASKS_DIR, RUNTIME_WEB_TASKS_DIR)


def _load_env_file() -> None:
    global ENV_PATH
    ENV_PATH = load_runtime_dotenv(override=True)


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    default_str = "true" if default else "false"
    return os.getenv(name, default_str).strip().lower() == "true"


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _serialize_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"

    text = "" if value is None else str(value)
    if text == "":
        return ""
    if re.search(r"\s|#|=", text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _normalize_model_name(value: str, fallback: str = "qwen-plus") -> str:
    candidate = str(value or "").strip() or fallback
    if "thinking" in candidate.lower():
        return fallback
    return candidate


def _write_env_updates(updates: Dict[str, Any]) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing_lines = []
    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    seen_keys = set()
    output_lines = []
    pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")

    for line in existing_lines:
        match = pattern.match(line)
        if not match:
            output_lines.append(line)
            continue

        key = match.group(1)
        if key in updates:
            output_lines.append(f"{key}={_serialize_env_value(updates[key])}")
            seen_keys.add(key)
        else:
            output_lines.append(line)

    for key, value in updates.items():
        if key in seen_keys:
            continue
        output_lines.append(f"{key}={_serialize_env_value(value)}")

    content = "\n".join(output_lines).rstrip()
    ENV_PATH.write_text(f"{content}\n" if content else "", encoding="utf-8")


def reload_runtime_config() -> Dict[str, Any]:
    """Reload environment-backed settings and refresh module globals."""
    _load_env_file()

    global MINERU_API_URL
    global MINERU_API_KEY
    global PDF_PARSE_BACKEND
    global REVIEW_API_URL
    global REVIEW_API_KEY
    global REVIEW_MODEL
    global RECHECK_LLM_API_URL
    global RECHECK_LLM_API_KEY
    global RECHECK_LLM_MODEL
    global RECHECK_VLM_API_URL
    global RECHECK_VLM_API_KEY
    global RECHECK_VLM_MODEL
    global RECHECK_LLM_ENABLED
    global RECHECK_VLM_ENABLED
    global SEARCH_API_URL
    global SEARCH_API_KEY
    global SEARCH_MODEL
    global VISION_API_URL
    global VISION_API_KEY
    global VISION_MODEL
    global RECHECK_API_URL
    global RECHECK_API_KEY
    global RECHECK_MODEL
    global TRANSLATION_API_URL
    global TRANSLATION_API_KEY
    global TRANSLATION_MODEL
    global QWEN_API_URL
    global QWEN_API_KEY
    global QWEN_MODEL
    global QWEN_REVIEW_MODEL
    global QWEN_VISION_MODEL
    global QWEN_RECHECK_MODEL
    global QWEN_TRANSLATION_MODEL
    global LLM_REQUEST_MIN_INTERVAL_SECONDS
    global CHUNK_MIN_SIZE
    global CHUNK_MAX_SIZE
    global LOCAL_CHUNK_MIN_SIZE
    global LOCAL_CHUNK_MAX_SIZE
    global REVIEW_PARALLELISM
    global REVIEW_EXCERPT_MAX_CHARS
    global SEND_IMAGES_TO_LLM
    global MAX_IMAGES_PER_CHUNK
    global ADJACENT_IMAGE_GROUP_SIZE
    global LLM_IMAGE_MIN_PIXELS
    global LLM_IMAGE_MAX_PIXELS
    global BBOX_MATCH_LIMIT
    global BBOX_OUTLINE_WIDTH
    global BBOX_EXPAND_X_PT
    global BBOX_EXPAND_Y_PT
    global LIVE_STREAM_SUMMARY
    global LIVE_STREAM_MODE
    global LIVE_STREAM_STEP_DELAY_MS
    global LIVE_STREAM_PREVIEW_CHARS
    global REPORT_LANGUAGE
    global REPORT_HTML_ENABLED
    global REPORT_TRANSLATION_BATCH_CHARS
    global REPORT_TRANSLATION_MAX_TOKENS
    global BBOX_NORMALIZED_SIZE
    global SAVE_BBOX_DEBUG_SCREENSHOTS
    global VISION_BBOX_PADDING
    global VISION_MAX_MATCH_IMAGES
    global VISION_PAGE_ZOOM
    global VISION_CROP_ZOOM
    global SEARCH_AGENT_ISSUE_TYPES
    global SEARCH_ENGINE
    global SEARCH_MAX_RESULTS
    global SERPER_API_KEY
    global LOG_LEVEL

    MINERU_API_URL = _env_str("MINERU_API_URL", "https://mineru.net/api/v4")
    MINERU_API_KEY = _env_str("MINERU_API_KEY", "")
    PDF_PARSE_BACKEND = "mineru"

    legacy_qwen_api_url = _env_str(
        "QWEN_API_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    legacy_qwen_api_key = _env_str("QWEN_API_KEY", "")
    legacy_qwen_model = _normalize_model_name(_env_str("QWEN_MODEL", "qwen-plus"))
    legacy_qwen_review_model = _normalize_model_name(
        _env_str("QWEN_REVIEW_MODEL", legacy_qwen_model),
    )
    legacy_vlm_api_url = _env_str("VISION_API_URL", "")
    legacy_vlm_api_key = _env_str("VISION_API_KEY", "")
    legacy_vlm_model = _env_str("VISION_MODEL", _env_str("QWEN_VISION_MODEL", "")).strip()
    legacy_recheck_llm_api_url = _env_str("RECHECK_API_URL", "")
    legacy_recheck_llm_api_key = _env_str("RECHECK_API_KEY", "")
    legacy_recheck_llm_model = _env_str("RECHECK_MODEL", _env_str("QWEN_RECHECK_MODEL", "")).strip()

    REVIEW_API_URL = _env_str("REVIEW_API_URL", legacy_qwen_api_url)
    REVIEW_API_KEY = _env_str("REVIEW_API_KEY", legacy_qwen_api_key)
    REVIEW_MODEL = _normalize_model_name(
        _env_str("REVIEW_MODEL", legacy_qwen_review_model or legacy_qwen_model),
    )
    RECHECK_LLM_API_URL = _env_str("RECHECK_LLM_API_URL", legacy_recheck_llm_api_url)
    RECHECK_LLM_API_KEY = _env_str("RECHECK_LLM_API_KEY", legacy_recheck_llm_api_key)
    RECHECK_LLM_MODEL = _env_str("RECHECK_LLM_MODEL", legacy_recheck_llm_model).strip()
    if RECHECK_LLM_MODEL:
        RECHECK_LLM_MODEL = _normalize_model_name(RECHECK_LLM_MODEL)
    RECHECK_VLM_API_URL = _env_str("RECHECK_VLM_API_URL", legacy_vlm_api_url)
    RECHECK_VLM_API_KEY = _env_str("RECHECK_VLM_API_KEY", legacy_vlm_api_key)
    RECHECK_VLM_MODEL = _env_str("RECHECK_VLM_MODEL", legacy_vlm_model).strip()

    RECHECK_LLM_ENABLED = bool(
        str(RECHECK_LLM_API_URL).strip()
        and str(RECHECK_LLM_API_KEY).strip()
        and str(RECHECK_LLM_MODEL).strip()
    )
    RECHECK_VLM_ENABLED = bool(
        str(RECHECK_VLM_API_URL).strip()
        and str(RECHECK_VLM_API_KEY).strip()
        and str(RECHECK_VLM_MODEL).strip()
    )

    SEARCH_API_URL = REVIEW_API_URL
    SEARCH_API_KEY = REVIEW_API_KEY
    SEARCH_MODEL = REVIEW_MODEL
    VISION_API_URL = RECHECK_VLM_API_URL
    VISION_API_KEY = RECHECK_VLM_API_KEY
    VISION_MODEL = RECHECK_VLM_MODEL
    RECHECK_API_URL = RECHECK_LLM_API_URL
    RECHECK_API_KEY = RECHECK_LLM_API_KEY
    RECHECK_MODEL = RECHECK_LLM_MODEL
    TRANSLATION_API_URL = REVIEW_API_URL
    TRANSLATION_API_KEY = REVIEW_API_KEY
    TRANSLATION_MODEL = REVIEW_MODEL

    QWEN_API_URL = REVIEW_API_URL
    QWEN_API_KEY = REVIEW_API_KEY
    QWEN_MODEL = REVIEW_MODEL
    QWEN_REVIEW_MODEL = REVIEW_MODEL
    QWEN_VISION_MODEL = RECHECK_VLM_MODEL
    QWEN_RECHECK_MODEL = RECHECK_LLM_MODEL
    QWEN_TRANSLATION_MODEL = REVIEW_MODEL
    LLM_REQUEST_MIN_INTERVAL_SECONDS = _env_float("LLM_REQUEST_MIN_INTERVAL_SECONDS", 0.0)

    CHUNK_MIN_SIZE = 8000
    CHUNK_MAX_SIZE = 12000
    LOCAL_CHUNK_MIN_SIZE = _env_int("LOCAL_CHUNK_MIN_SIZE", 4000)
    LOCAL_CHUNK_MAX_SIZE = _env_int("LOCAL_CHUNK_MAX_SIZE", 6000)
    if LOCAL_CHUNK_MIN_SIZE < 1:
        LOCAL_CHUNK_MIN_SIZE = 1
    if LOCAL_CHUNK_MAX_SIZE < LOCAL_CHUNK_MIN_SIZE:
        LOCAL_CHUNK_MAX_SIZE = LOCAL_CHUNK_MIN_SIZE

    REVIEW_PARALLELISM = _env_int("REVIEW_PARALLELISM", 2)
    REVIEW_EXCERPT_MAX_CHARS = _env_int("REVIEW_EXCERPT_MAX_CHARS", 6500)
    SEND_IMAGES_TO_LLM = _env_bool("SEND_IMAGES_TO_LLM", False)
    MAX_IMAGES_PER_CHUNK = _env_int("MAX_IMAGES_PER_CHUNK", 12)
    ADJACENT_IMAGE_GROUP_SIZE = _env_int("ADJACENT_IMAGE_GROUP_SIZE", 3)
    LLM_IMAGE_MIN_PIXELS = _env_int("LLM_IMAGE_MIN_PIXELS", 65536)
    LLM_IMAGE_MAX_PIXELS = _env_int("LLM_IMAGE_MAX_PIXELS", 1048576)

    BBOX_MATCH_LIMIT = _env_int("BBOX_MATCH_LIMIT", 3)
    BBOX_OUTLINE_WIDTH = _env_float("BBOX_OUTLINE_WIDTH", 3.0)
    BBOX_EXPAND_X_PT = _env_float("BBOX_EXPAND_X_PT", 4.0)
    BBOX_EXPAND_Y_PT = _env_float("BBOX_EXPAND_Y_PT", 3.0)
    LIVE_STREAM_SUMMARY = _env_bool("LIVE_STREAM_SUMMARY", True)
    LIVE_STREAM_MODE = _env_str("LIVE_STREAM_MODE", "progress").lower()
    LIVE_STREAM_STEP_DELAY_MS = _env_int("LIVE_STREAM_STEP_DELAY_MS", 250)
    LIVE_STREAM_PREVIEW_CHARS = _env_int("LIVE_STREAM_PREVIEW_CHARS", 120)

    REPORT_LANGUAGE = _env_str("REPORT_LANGUAGE", "zh").lower()
    REPORT_HTML_ENABLED = _env_bool("REPORT_HTML_ENABLED", True)
    REPORT_TRANSLATION_BATCH_CHARS = _env_int("REPORT_TRANSLATION_BATCH_CHARS", 3000)
    REPORT_TRANSLATION_MAX_TOKENS = _env_int("REPORT_TRANSLATION_MAX_TOKENS", 6000)
    BBOX_NORMALIZED_SIZE = _env_int("BBOX_NORMALIZED_SIZE", 1000)
    SAVE_BBOX_DEBUG_SCREENSHOTS = _env_bool("SAVE_BBOX_DEBUG_SCREENSHOTS", True)
    VISION_BBOX_PADDING = _env_int("VISION_BBOX_PADDING", 24)
    VISION_MAX_MATCH_IMAGES = _env_int("VISION_MAX_MATCH_IMAGES", 2)
    VISION_PAGE_ZOOM = _env_float("VISION_PAGE_ZOOM", 1.5)
    VISION_CROP_ZOOM = _env_float("VISION_CROP_ZOOM", 2.2)

    SEARCH_AGENT_ISSUE_TYPES = _env_list(
        "SEARCH_AGENT_ISSUE_TYPES",
        "Background Knowledge,Citation Fabrication,Claim Distortion",
    )
    SEARCH_ENGINE = _env_str("SEARCH_ENGINE", "duckduckgo").lower()
    SEARCH_MAX_RESULTS = _env_int("SEARCH_MAX_RESULTS", 5)
    SERPER_API_KEY = _env_str("SERPER_API_KEY", "")

    LOG_LEVEL = _env_str("LOG_LEVEL", "INFO")

    return get_runtime_config()


def get_runtime_config(mask_secrets: bool = False) -> Dict[str, Any]:
    """Return configuration values used by the web UI."""
    values = {
        "mineru_api_url": MINERU_API_URL,
        "mineru_api_key": MINERU_API_KEY,
        "review_api_url": REVIEW_API_URL,
        "review_api_key": REVIEW_API_KEY,
        "review_model": REVIEW_MODEL,
        "recheck_llm_api_url": RECHECK_LLM_API_URL,
        "recheck_llm_api_key": RECHECK_LLM_API_KEY,
        "recheck_llm_model": RECHECK_LLM_MODEL,
        "recheck_vlm_api_url": RECHECK_VLM_API_URL,
        "recheck_vlm_api_key": RECHECK_VLM_API_KEY,
        "recheck_vlm_model": RECHECK_VLM_MODEL,
        "recheck_llm_enabled": RECHECK_LLM_ENABLED,
        "recheck_vlm_enabled": RECHECK_VLM_ENABLED,
        "qwen_api_url": QWEN_API_URL,
        "qwen_api_key": QWEN_API_KEY,
        "qwen_model": QWEN_MODEL,
        "qwen_review_model": QWEN_REVIEW_MODEL,
        "qwen_vision_model": QWEN_VISION_MODEL,
        "qwen_recheck_model": QWEN_RECHECK_MODEL,
        "qwen_translation_model": QWEN_TRANSLATION_MODEL,
        "llm_request_min_interval_seconds": LLM_REQUEST_MIN_INTERVAL_SECONDS,
        "report_language": REPORT_LANGUAGE,
        "search_engine": SEARCH_ENGINE,
        "serper_api_key": SERPER_API_KEY,
        "review_parallelism": REVIEW_PARALLELISM,
    }
    if not mask_secrets:
        return values

    masked = dict(values)
    for field in SECRET_FIELDS:
        value = masked.get(field, "")
        if value:
            masked[field] = f"{value[:4]}...{value[-2:]}" if len(value) > 6 else "******"
    return masked


def update_runtime_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a subset of web-editable settings and reload module globals."""
    normalized_payload = dict(payload or {})
    if "review_model" not in normalized_payload:
        legacy_review_model = normalized_payload.get("qwen_review_model") or normalized_payload.get("qwen_model")
        if legacy_review_model is not None:
            normalized_payload["review_model"] = legacy_review_model
    for legacy_field, current_field in LEGACY_CONFIG_ALIASES.items():
        if current_field not in normalized_payload and legacy_field in normalized_payload:
            normalized_payload[current_field] = normalized_payload[legacy_field]

    env_updates: Dict[str, Any] = {}
    for field, env_name in CONFIG_FIELD_MAP.items():
        if field not in normalized_payload:
            continue
        value = normalized_payload[field]
        if field == "report_language":
            value = "en" if str(value).lower() == "en" else "zh"
        elif field == "review_parallelism":
            try:
                value = max(1, int(value))
            except (TypeError, ValueError):
                continue
        elif field == "llm_request_min_interval_seconds":
            try:
                value = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
        elif field.endswith("_model"):
            value = str(value).strip()
            if value:
                value = _normalize_model_name(value)
        elif value is None:
            value = ""
        else:
            value = str(value).strip()
        env_updates[env_name] = value
        os.environ[env_name] = "true" if value is True else "false" if value is False else str(value)

    if env_updates:
        _write_env_updates(env_updates)

    return reload_runtime_config()
reload_runtime_config()
