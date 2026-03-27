from __future__ import annotations

import argparse
import asyncio
import builtins
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from draftclaw import cli
from draftclaw._core.config import build_config
from draftclaw._core.contracts import ModeResult
from draftclaw._core.enums import ModeName
from draftclaw._runtime.pdf_versions import PdfVersionRegistry


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
        "reparse_pdf": None,
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


def test_cli_review_uses_yaml_defaults(monkeypatch, capsys, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    run_root = _artifact_dir("cli_yaml")
    input_path = tmp_path / "paper.txt"
    input_path.write_text("alpha", encoding="utf-8")

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            captured["config_path"] = config_path
            captured["llm_override"] = llm_override
            captured["working_dir"] = working_dir
            self.config = build_config(
                {
                    "run": {
                        "input_file": str(input_path),
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
            self.working_dir = Path(working_dir or tmp_path / "output")

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
    assert captured["review_input"] == str(input_path.resolve())
    assert captured["review_mode"] == ModeName.STANDARD
    assert captured["review_run_name"] == "yaml_run"
    assert "run_root" in capsys.readouterr().out


def test_cli_review_prefers_explicit_overrides(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    run_root = _artifact_dir("cli_override")
    input_path = tmp_path / "override.txt"
    input_path.write_text("beta", encoding="utf-8")

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            captured["config_path"] = config_path
            captured["llm_override"] = llm_override
            captured["working_dir"] = working_dir
            self.config = build_config(
                {
                    "run": {
                        "input_file": "paper.txt",
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
            self.working_dir = Path(working_dir or tmp_path / "output")

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
                input=str(input_path),
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
    assert captured["review_input"] == str(input_path.resolve())
    assert captured["review_mode"] == ModeName.FAST
    assert captured["review_run_name"] == "override_run"


def test_cli_review_accepts_deep_mode_override(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    run_root = _artifact_dir("cli_deep")
    input_path = tmp_path / "paper.txt"
    input_path.write_text("gamma", encoding="utf-8")

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            self.config = build_config(
                {
                    "run": {
                        "input_file": str(input_path),
                        "mode": "standard",
                    },
                    "llm": {
                        "api_key": "test-key",
                        "base_url": "https://example.com/v1",
                        "model": "demo-model",
                    },
                }
            )
            self.working_dir = Path(working_dir or tmp_path / "output")

        async def review(self, *, input_path: str, mode: ModeName, run_name: str | None = None):
            captured["review_mode"] = mode
            return ModeResult(mode=mode), run_root

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)

    exit_code = asyncio.run(cli._run_async(_make_args(mode="deep", input=str(input_path))))

    assert exit_code == 0
    assert captured["review_mode"] == ModeName.DEEP


def test_cli_review_requires_input_from_yaml_or_override(monkeypatch, tmp_path: Path) -> None:
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
            self.working_dir = Path(working_dir or tmp_path / "output")

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)

    with pytest.raises(cli.CLIConfigurationError, match="run.input_file"):
        asyncio.run(cli._run_async(_make_args()))


def test_cli_review_prompts_before_reparsing_changed_pdf(monkeypatch, capsys, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    run_root = _artifact_dir("cli_pdf_prompt")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"first")
    registry = PdfVersionRegistry(workdir)
    registry.record(pdf_path)
    pdf_path.write_bytes(b"second")

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            self.config = build_config(
                {
                    "run": {
                        "input_file": str(pdf_path),
                        "mode": "standard",
                    },
                    "llm": {
                        "api_key": "test-key",
                        "base_url": "https://example.com/v1",
                        "model": "demo-model",
                    },
                }
            )
            self.working_dir = Path(working_dir or workdir)

        async def review(self, *, input_path: str, mode: ModeName, run_name: str | None = None):
            captured["review_input"] = input_path
            return ModeResult(mode=mode), run_root

    prompts: list[str] = []

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or "y")
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))

    exit_code = asyncio.run(
        cli._run_async(
            _make_args(
                input=str(pdf_path),
                working_dir=str(workdir),
            )
        )
    )

    assert exit_code == 0
    assert captured["review_input"] == str(pdf_path.resolve())
    assert "different content" in prompts[0]
    capsys.readouterr()
    assert not PdfVersionRegistry(workdir).inspect(pdf_path).changed


def test_cli_review_can_cancel_reparse_for_changed_pdf(monkeypatch, capsys, tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"first")
    PdfVersionRegistry(workdir).record(pdf_path)
    pdf_path.write_bytes(b"second")
    reviewed = False

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            self.config = build_config(
                {
                    "run": {
                        "input_file": str(pdf_path),
                        "mode": "standard",
                    },
                    "llm": {
                        "api_key": "test-key",
                        "base_url": "https://example.com/v1",
                        "model": "demo-model",
                    },
                }
            )
            self.working_dir = Path(working_dir or workdir)

        async def review(self, *, input_path: str, mode: ModeName, run_name: str | None = None):
            nonlocal reviewed
            reviewed = True
            return ModeResult(mode=mode), _artifact_dir("cli_pdf_cancel")

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)

    exit_code = asyncio.run(
        cli._run_async(
            _make_args(
                input=str(pdf_path),
                working_dir=str(workdir),
                reparse_pdf=False,
            )
        )
    )

    assert exit_code == 1
    assert reviewed is False
    assert "Review cancelled." in capsys.readouterr().out


def test_cli_review_requires_explicit_choice_for_changed_pdf_in_noninteractive_mode(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"first")
    PdfVersionRegistry(workdir).record(pdf_path)
    pdf_path.write_bytes(b"second")

    class FakeApp:
        def __init__(self, config_path, llm_override=None, working_dir=None) -> None:  # noqa: ANN001
            self.config = build_config(
                {
                    "run": {
                        "input_file": str(pdf_path),
                        "mode": "standard",
                    },
                    "llm": {
                        "api_key": "test-key",
                        "base_url": "https://example.com/v1",
                        "model": "demo-model",
                    },
                }
            )
            self.working_dir = Path(working_dir or workdir)

    monkeypatch.setattr(cli, "DraftClawApp", FakeApp)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    with pytest.raises(cli.CLIConfigurationError, match="--reparse-pdf"):
        asyncio.run(cli._run_async(_make_args(input=str(pdf_path), working_dir=str(workdir))))
