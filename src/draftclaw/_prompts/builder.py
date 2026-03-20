from __future__ import annotations

from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, Template


class PromptBuilder:
    def __init__(self, prompts_root: str | Path | Traversable) -> None:
        if isinstance(prompts_root, (str, Path)):
            self.prompts_root: Path | Traversable = Path(prompts_root)
        else:
            self.prompts_root = prompts_root

    def load(self, relative_path: str) -> str:
        path = self.prompts_root.joinpath(*Path(relative_path).parts)
        if not path.is_file():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8")

    def render(self, relative_path: str, variables: dict[str, Any]) -> str:
        raw = self.load(relative_path)
        template = Template(raw, undefined=StrictUndefined)
        return template.render(**variables)

    def build_messages(
        self,
        *,
        system_files: list[str],
        user_file: str,
        variables: dict[str, Any],
    ) -> tuple[list[dict[str, str]], str]:
        system_text = "\n\n".join(self.load(path) for path in system_files)
        user_text = self.render(user_file, variables)
        rendered_prompt = f"# System Prompt\n{system_text}\n\n# User Prompt\n{user_text}\n"
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
        return messages, rendered_prompt
