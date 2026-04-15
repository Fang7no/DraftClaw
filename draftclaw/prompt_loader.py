"""
Prompt loading helpers for agent prompt files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from config import PROMPTS_DIR


def load_prompt_text(filename: str, fallback: str = "") -> str:
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return fallback


def parse_prompt_sections(filename: str) -> Dict[str, str]:
    content = load_prompt_text(filename)
    if not content:
        return {}

    sections: Dict[str, list[str]] = {}
    current_section = ""
    seen_sections = set()

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip().lower()
            if not current_section:
                raise ValueError(f"Prompt file `{filename}` contains an empty section header.")
            if current_section in seen_sections:
                raise ValueError(f"Prompt file `{filename}` contains duplicate section `{current_section}`.")
            seen_sections.add(current_section)
            sections[current_section] = []
            continue

        if current_section:
            sections[current_section].append(line)

    return {
        section_name: "\n".join(lines).strip()
        for section_name, lines in sections.items()
    }


def load_prompt_section_text(filename: str, section: str, fallback: str = "") -> str:
    sections = parse_prompt_sections(filename)
    if not sections:
        return fallback

    target_section = str(section or "").strip().lower()
    return sections.get(target_section, "") or fallback


def render_prompt_template(filename: str, fallback: str = "", **values: Any) -> str:
    template = load_prompt_text(filename, fallback=fallback)
    return _render_values(template, **values)


def render_prompt_section_template(
    filename: str,
    section: str,
    fallback: str = "",
    **values: Any,
) -> str:
    template = load_prompt_section_text(filename, section, fallback=fallback)
    return _render_values(template, **values)


def _render_values(template: str, **values: Any) -> str:
    rendered = template
    for key, value in values.items():
        pattern = r"{{\s*" + re.escape(str(key)) + r"\s*}}"
        rendered = re.sub(pattern, lambda _match, replacement=str(value): replacement, rendered)
    return rendered
