from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from draftclaw._core.config import AppConfig, build_config, load_config
from draftclaw.web.models import STATUS_COMPLETED, STATUS_INTERRUPTED, STATUS_QUEUED, STATUS_RUNNING, STATUS_STOPPED, Job


class _JsonEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


def _final_progress(status: str, error_detail: str | None = None) -> tuple[str, str, str | None, int | None, int | None]:
    if status == STATUS_COMPLETED:
        return ("reporting", "\u5df2\u5b8c\u6210", "\u62a5\u544a\u5df2\u751f\u6210", 100, 100)
    if status == STATUS_STOPPED:
        return (STATUS_STOPPED, "\u5df2\u505c\u6b62", "\u4efb\u52a1\u5df2\u624b\u52a8\u505c\u6b62", None, None)
    if status == STATUS_INTERRUPTED:
        return (
            STATUS_INTERRUPTED,
            "\u5904\u7406\u5931\u8d25",
            error_detail or "\u4efb\u52a1\u6267\u884c\u4e2d\u65ad\uff0c\u8bf7\u68c0\u67e5\u914d\u7f6e\u540e\u91cd\u65b0\u5165\u961f\u3002",
            None,
            None,
        )
    return (status, status, error_detail, None, None)


class JobStore:
    def __init__(self, db_path: str | Path, *, settings_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).resolve()
        self.settings_path = Path(settings_path).resolve() if settings_path else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    input_filename TEXT NOT NULL,
                    input_path TEXT NOT NULL,
                    upload_dir TEXT NOT NULL,
                    config_snapshot TEXT NOT NULL,
                    pid INTEGER,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    progress_stage TEXT NOT NULL DEFAULT 'queued',
                    progress_label TEXT NOT NULL DEFAULT '\u7b49\u5f85\u5f00\u59cb',
                    progress_detail TEXT,
                    progress_current INTEGER,
                    progress_total INTEGER,
                    result_html_path TEXT,
                    run_dir TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def save_settings(self, config_snapshot: dict[str, Any] | AppConfig) -> None:
        if hasattr(config_snapshot, "model_dump"):
            # Store unmasked full config for load_settings()
            unmasked = config_snapshot.model_dump(mode="json")
            config_snapshot_to_save = config_snapshot.model_dump()
        else:
            unmasked = config_snapshot
            config_snapshot_to_save = config_snapshot
        with sqlite3.connect(str(self.db_path)) as conn:
            raw = json.dumps(config_snapshot_to_save, ensure_ascii=False, cls=_JsonEncoder)
            unmasked_raw = json.dumps(unmasked, ensure_ascii=False)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('settings', ?)",
                (raw,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('settings_full', ?)",
                (unmasked_raw,),
            )
        # YAML file is written by the caller (web app), not here

    def load_settings(self) -> AppConfig:
        def _config_has_live_secrets(config: AppConfig) -> bool:
            llm_api_key = config.llm.api_key.strip()
            if llm_api_key in {"", "***", "your_api_key"}:
                return False
            if config.parser.pdf_parse_mode != "accurate":
                return True
            parser_api_key = config.parser.paddleocr_api_key.strip()
            return parser_api_key != "***"

        # Try DB first (most recent saved settings)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            # Prefer settings_full (unmasked) over settings (masked)
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'settings_full' LIMIT 1"
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = 'settings' LIMIT 1"
                ).fetchone()
        if row is not None:
            data = json.loads(row["value"])
            config = build_config(data)
            if _config_has_live_secrets(config):
                return config
            if self.settings_path is not None and self.settings_path.exists():
                try:
                    yaml_config = load_config(self.settings_path)
                except Exception:
                    return config
                if _config_has_live_secrets(yaml_config):
                    return yaml_config
            return config
        # Fall back to YAML file
        if self.settings_path is None or not self.settings_path.exists():
            return build_config({})
        return load_config(self.settings_path)

    def create_job(
        self,
        *,
        job_id: str,
        mode: str,
        input_filename: str,
        input_path: str,
        upload_dir: str,
        config_snapshot: dict[str, Any] | AppConfig,
    ) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        if hasattr(config_snapshot, "model_dump"):
            config_snapshot = config_snapshot.model_dump()
        job = Job(
            job_id=job_id,
            status=STATUS_QUEUED,
            mode=mode,
            input_filename=input_filename,
            input_path=input_path,
            upload_dir=upload_dir,
            config_snapshot=config_snapshot,
            attempt_count=1,
            progress_stage=STATUS_QUEUED,
            progress_label="\u7b49\u5f85\u5f00\u59cb",
            created_at=now,
            updated_at=now,
        )
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, status, mode, input_filename, input_path, upload_dir,
                    config_snapshot, attempt_count, progress_stage, progress_label,
                    progress_detail, progress_current, progress_total,
                    result_html_path, run_dir, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.status,
                    job.mode,
                    job.input_filename,
                    job.input_path,
                    job.upload_dir,
                    json.dumps(job.config_snapshot, ensure_ascii=False),
                    job.attempt_count,
                    job.progress_stage,
                    job.progress_label,
                    job.progress_detail,
                    job.progress_current,
                    job.progress_total,
                    job.result_html_path,
                    job.run_dir,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    def get_job(self, job_id: str) -> Job:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return self._row_to_job(row)

    def list_jobs(self) -> list[Job]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at ASC"
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def mark_running(
        self,
        job_id: str,
        pid: int,
        *,
        label: str | None = None,
        detail: str | None = None,
    ) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE jobs SET status = ?, pid = ?, progress_stage = ?,
                progress_label = ?, progress_detail = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    STATUS_RUNNING,
                    pid,
                    "parsing",
                    label or "\u6587\u6863\u89e3\u6790\u4e2d",
                    detail,
                    now,
                    job_id,
                ),
            )
        return self.get_job(job_id)

    def update_progress(
        self,
        job_id: str,
        stage: str,
        label: str,
        detail: str | None,
        current: int | None,
        total: int | None,
    ) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE jobs SET progress_stage = ?, progress_label = ?,
                progress_detail = ?, progress_current = ?, progress_total = ?,
                updated_at = ?
                WHERE job_id = ?
                """,
                (stage, label, detail, current, total, now, job_id),
            )
        return self.get_job(job_id)

    def finalize_job(
        self,
        job_id: str,
        status: str,
        run_dir: str,
        result_html_path: str,
        *,
        error_detail: str | None = None,
    ) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        progress_stage, progress_label, progress_detail, progress_current, progress_total = _final_progress(
            status,
            error_detail,
        )
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE jobs SET status = ?, run_dir = ?, result_html_path = ?, pid = NULL,
                progress_stage = ?, progress_label = ?, progress_detail = ?,
                progress_current = ?, progress_total = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    run_dir,
                    result_html_path,
                    progress_stage,
                    progress_label,
                    progress_detail,
                    progress_current,
                    progress_total,
                    now,
                    job_id,
                ),
            )
        return self.get_job(job_id)

    def request_stop(self, job_id: str) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?
                """,
                (STATUS_STOPPED, now, job_id),
            )
        return self.get_job(job_id)

    def requeue_job(self, job_id: str, config_snapshot: dict[str, Any] | AppConfig) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        if hasattr(config_snapshot, "model_dump"):
            config_snapshot_to_save = config_snapshot.model_dump(mode="json")
        else:
            config_snapshot_to_save = config_snapshot
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE jobs SET status = ?, attempt_count = attempt_count + 1,
                config_snapshot = ?, progress_stage = ?, progress_label = ?,
                progress_detail = ?, progress_current = ?, progress_total = ?,
                pid = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    STATUS_QUEUED,
                    json.dumps(config_snapshot_to_save, ensure_ascii=False),
                    STATUS_QUEUED,
                    "\u7b49\u5f85\u5f00\u59cb",
                    None,
                    None,
                    None,
                    now,
                    job_id,
                ),
            )
        return self.get_job(job_id)

    def delete_job(self, job_id: str) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            status=row["status"],
            mode=row["mode"],
            input_filename=row["input_filename"],
            input_path=row["input_path"],
            upload_dir=row["upload_dir"],
            config_snapshot=json.loads(row["config_snapshot"]),
            pid=row["pid"],
            attempt_count=row["attempt_count"],
            progress_stage=row["progress_stage"],
            progress_label=row["progress_label"],
            progress_detail=row["progress_detail"],
            progress_current=row["progress_current"],
            progress_total=row["progress_total"],
            result_html_path=row["result_html_path"],
            run_dir=row["run_dir"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
