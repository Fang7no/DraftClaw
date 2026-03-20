from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class LLMCache:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self.cache_dir / f"{key}.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

