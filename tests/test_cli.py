from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from draftclaw import cli
from draftclaw._core.config import build_config
from draftclaw._core.contracts import ModeResult
from draftclaw._core.enums import ModeName


def _make_args(**overrides) -> argparse.Namespace:
    payload = {
        "config": None,
        "working_dir": None,
        "api_key": None,
        "base_url": None,
        "model": None,
        "command": "review",
        "input": None,
        "mode": None,
        "run_name": None,
        "result": None,
        "json": False,
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_cli_review_uses_yaml_defaults(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    run_root = _artifact_dir("cli_yaml")

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            captured["config_path"] = config_path
            captured["llm_override"] = llm_override
            captured["working_dir"] = working_dir
            self.config = build_config(
                {
                    "run": {
                        "input_file": "paper.pdf",
                        "mode": "standard",
                        "run_name": "yaml_run",
                    },
                    "llm": {
                        "api_key": "test-key",
                        "base_url": "https://example.com/v1",
                        "model": "demo-model",
                    },
                }
            )

        async def review(self, *, input_path: str, mode: ModeName, run_name: str | None = None):
            captured["review_input"] = input_path
            captured["review_mode"] = mode
            captured["review_run_name"] = run_name
            return ModeResult(mode=mode), run_root

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)

    exit_code = asyncio.run(cli._run_async(_make_args()))

    assert exit_code == 0
    assert captured["llm_override"] is None
    assert captured["working_dir"] is None
    assert captured["review_input"] == "paper.pdf"
    assert captured["review_mode"] == ModeName.STANDARD
    assert captured["review_run_name"] == "yaml_run"
    assert "run_root" in capsys.readouterr().out


def test_cli_review_prefers_explicit_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}
    run_root = _artifact_dir("cli_override")

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            captured["config_path"] = config_path
            captured["llm_override"] = llm_override
            captured["working_dir"] = working_dir
            self.config = build_config(
                {
                    "run": {
                        "input_file": "paper.pdf",
                        "mode": "standard",
                        "run_name": "yaml_run",
                    },
                    "llm": {
                        "api_key": "test-key",
                        "base_url": "https://example.com/v1",
                        "model": "demo-model",
                    },
                }
            )

        async def review(self, *, input_path: str, mode: ModeName, run_name: str | None = None):
            captured["review_input"] = input_path
            captured["review_mode"] = mode
            captured["review_run_name"] = run_name
            return ModeResult(mode=mode), run_root

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)

    exit_code = asyncio.run(
        cli._run_async(
            _make_args(
                config="custom.yaml",
                working_dir="custom-output",
                api_key="override-key",
                base_url="https://override.example/v1",
                model="override-model",
                input="override.pdf",
                mode="fast",
                run_name="override_run",
            )
        )
    )

    assert exit_code == 0
    assert captured["config_path"] == "custom.yaml"
    assert captured["working_dir"] == "custom-output"
    assert captured["llm_override"] == {
        "api_key": "override-key",
        "base_url": "https://override.example/v1",
        "model": "override-model",
    }
    assert captured["review_input"] == "override.pdf"
    assert captured["review_mode"] == ModeName.FAST
    assert captured["review_run_name"] == "override_run"


def test_cli_review_requires_input_from_yaml_or_override(monkeypatch) -> None:
    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            self.config = build_config(
                {
                    "run": {
                        "input_file": "",
                        "mode": "standard",
                    },
                    "llm": {
                        "api_key": "test-key",
                        "base_url": "https://example.com/v1",
                        "model": "demo-model",
                    },
                }
            )

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)

    with pytest.raises(cli.CLIConfigurationError, match="run.input_file"):
        asyncio.run(cli._run_async(_make_args()))
