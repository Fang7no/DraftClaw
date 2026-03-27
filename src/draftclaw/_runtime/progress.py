from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROGRESS_STAGE_PARSING = "parsing"
PROGRESS_STAGE_ANALYZING = "analyzing"
PROGRESS_STAGE_REPORTING = "reporting"


@dataclass(slots=True, frozen=True)
class ProgressEvent:
    stage: str
    label: str
    detail: str | None = None
    current: int | None = None
    total: int | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def emit_progress(
    callback: ProgressCallback | None,
    *,
    stage: str,
    label: str,
    detail: str | None = None,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if callback is None:
        return
    callback(
        ProgressEvent(
            stage=stage,
            label=label,
            detail=detail,
            current=current,
            total=total,
        )
    )


def parsing_label_for_path(input_path: str | Path) -> str:
    return "PDF\u89e3\u6790\u4e2d" if Path(input_path).suffix.lower() == ".pdf" else "\u6587\u6863\u89e3\u6790\u4e2d"


def chunk_progress_detail(*, current: int, total: int) -> str:
    return "\u6b63\u5728\u6267\u884c Agent \u68c0\u6d4b"
