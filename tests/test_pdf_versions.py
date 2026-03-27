from __future__ import annotations

from pathlib import Path

from draftclaw._runtime.pdf_versions import PdfVersionRegistry


def test_pdf_version_registry_detects_same_name_content_change(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    registry = PdfVersionRegistry(root)

    first = tmp_path / "paper.pdf"
    first.write_bytes(b"first")
    recorded = registry.record(first)
    assert recorded.changed is False

    first.write_bytes(b"second")
    status = registry.inspect(first)
    assert status.changed is True
    assert status.previous_file_size == len(b"first")
    assert status.previous_seen_at is not None


def test_pdf_version_registry_is_case_insensitive_by_filename(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    registry = PdfVersionRegistry(root)

    original = tmp_path / "Paper.PDF"
    original.write_bytes(b"alpha")
    registry.record(original)

    changed = tmp_path / "paper.pdf"
    changed.write_bytes(b"beta")
    status = registry.inspect(changed)
    assert status.changed is True
