"""
Shared environment-file discovery for DraftClaw.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


def resolve_env_path() -> Path:
    """Return the canonical env file path for this runtime."""
    explicit_path = os.getenv("DRAFTCLAW_ENV_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()

    project_env = PROJECT_DIR / ".env"
    if project_env.exists():
        return project_env

    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env

    return PACKAGE_DIR / ".env"


def load_runtime_dotenv(*, override: bool = True) -> Path:
    """Load the active env file if python-dotenv is available."""
    env_path = resolve_env_path()
    if load_dotenv:
        load_dotenv(env_path, override=override)
    return env_path
