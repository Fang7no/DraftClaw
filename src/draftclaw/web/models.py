from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"
STATUS_COMPLETED = "completed"
STATUS_INTERRUPTED = "interrupted"

_STAGE_TO_LABEL = {
    "queued": "\u7b49\u5f85\u5f00\u59cb",  # 等待开始
    "parsing": "\u6587\u6863\u89e3\u6790\u4e2d",  # 文档解析中
    "analyzing": "\u6587\u6863\u5206\u6790\u4e2d",  # 文档分析中
    "reporting": "\u62a5\u544a\u751f\u6210\u4e2d",  # 报告生成中
}


@dataclass(slots=True)
class Job:
    job_id: str
    status: str
    mode: str
    input_filename: str
    input_path: str
    upload_dir: str
    config_snapshot: dict[str, Any]
    pid: int | None = None
    attempt_count: int = 1
    progress_stage: str = STATUS_QUEUED
    progress_label: str = "\u7b49\u5f85\u5f00\u59cb"
    progress_detail: str | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    result_html_path: str | None = None
    run_dir: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at

    @property
    def progress(self) -> dict[str, Any]:
        percent = 0
        if self.status == STATUS_COMPLETED:
            percent = 100
        elif self.progress_stage == STATUS_QUEUED:
            percent = 0
        elif self.progress_stage == "parsing":
            percent = 16
        elif self.progress_stage == "analyzing":
            if self.progress_total and self.progress_total > 0:
                bounded_current = max(0, min(self.progress_current or 0, self.progress_total))
                percent = 24 + int(bounded_current / self.progress_total * 60)
            else:
                percent = 54
        elif self.progress_stage == "reporting":
            percent = 92
        else:
            percent = 0

        return {
            "label": self.progress_label,
            "detail": self.progress_detail,
            "percent": percent,
            "stage": self.progress_stage,
        }

    def to_dict(self) -> dict[str, Any]:
        report_url = None
        if self.result_html_path:
            report_url = f"/reports/{self.job_id}"

        return {
            "job_id": self.job_id,
            "status": self.status,
            "mode": self.mode,
            "input_filename": self.input_filename,
            "progress": self.progress,
            "report_url": report_url,
            "attempt_count": self.attempt_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
