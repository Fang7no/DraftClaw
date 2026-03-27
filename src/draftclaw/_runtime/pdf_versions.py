from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


@dataclass(slots=True)
class PdfVersionStatus:
    filename: str
    sha256: str
    file_size: int
    previous_sha256: str | None = None
    previous_file_size: int | None = None
    previous_seen_at: str | None = None

    @property
    def changed(self) -> bool:
        return self.previous_sha256 is not None and self.previous_sha256 != self.sha256


class PdfVersionRegistry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / ".cache" / "pdf_versions.json"

    def inspect(self, pdf_path: str | Path) -> PdfVersionStatus:
        path = Path(pdf_path).resolve()
        stat = path.stat()
        sha256 = self._hash_file(path)
        payload = self._load()
        record = payload.get(self._key(path.name))
        return PdfVersionStatus(
            filename=path.name,
            sha256=sha256,
            file_size=stat.st_size,
            previous_sha256=self._coerce_str(record, "sha256"),
            previous_file_size=self._coerce_int(record, "file_size"),
            previous_seen_at=self._coerce_str(record, "seen_at"),
        )

    def record(self, pdf_path: str | Path, *, seen_at: str | None = None) -> PdfVersionStatus:
        path = Path(pdf_path).resolve()
        status = self.inspect(path)
        payload = self._load()
        payload[self._key(path.name)] = {
            "filename": path.name,
            "sha256": status.sha256,
            "file_size": status.file_size,
            "path": str(path),
            "seen_at": seen_at or datetime.now(timezone.utc).isoformat(),
        }
        self._save(payload)
        return status

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        normalized: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized[key] = value
        return normalized

    def _save(self, payload: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(self.path.parent), suffix=".tmp") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _key(filename: str) -> str:
        return filename.strip().lower()

    @staticmethod
    def _coerce_str(record: dict[str, Any] | None, key: str) -> str | None:
        if not isinstance(record, dict):
            return None
        value = record.get(key)
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _coerce_int(record: dict[str, Any] | None, key: str) -> int | None:
        if not isinstance(record, dict):
            return None
        value = record.get(key)
        return value if isinstance(value, int) and value >= 0 else None
