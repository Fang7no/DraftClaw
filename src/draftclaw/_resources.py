from __future__ import annotations

from pathlib import Path
from importlib.resources import files
from importlib.resources.abc import Traversable


def package_resources_root() -> Traversable:
    return files("draftclaw").joinpath("resources")


def package_prompts_root() -> Traversable:
    return package_resources_root().joinpath("prompts")


def package_default_config_path() -> Path:
    return Path(__file__).resolve().parent.joinpath("resources", "configs", "default.yaml")


def package_default_config_file() -> Traversable:
    return package_resources_root().joinpath("configs").joinpath("default.yaml")
