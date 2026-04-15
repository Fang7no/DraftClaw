"""
Task management with SQLite persistence for DraftClaw Web UI.
"""

import json
import sqlite3
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import CACHE_DIR, LOGS_DIR, WEB_TASKS_DIR, normalize_runtime_path, normalize_runtime_value
from issue_review import issue_is_dropped
from logger import AgentLogger

# Canonical runtime storage
WEB_TASKS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = WEB_TASKS_DIR / "tasks.db"


def get_db_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            config TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            pdf_path TEXT,
            pdf_name TEXT,
            progress TEXT NOT NULL DEFAULT '{}',
            logs TEXT NOT NULL DEFAULT '[]',
            result TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def dict_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a sqlite3.Row to a dict."""
    return dict(row)


DEFAULT_PROGRESS = {
    "percent": 0,
    "phase": "",
    "message": "",
    "current_chunk": 0,
    "total_chunks": 0,
}


class TaskCancelled(RuntimeError):
    """Raised inside the worker when a task is cancelled by the user."""


class Task:
    """Represents a single review task."""

    def __init__(
        self,
        task_id: str,
        mode: str,
        config: Dict[str, Any],
        pdf_path: Optional[str] = None,
        pdf_name: Optional[str] = None,
    ):
        self.id = task_id
        self.mode = mode
        self.config = config
        self.pdf_path = pdf_path
        self.pdf_name = pdf_name
        self.status = "pending"
        self.progress: Dict[str, Any] = dict(DEFAULT_PROGRESS)
        self.logs: List[Dict[str, Any]] = []
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now().isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "config": self.config,
            "pdf_path": self.pdf_path,
            "pdf_name": self.pdf_name,
            "status": self.status,
            "progress": self.progress,
            "logs": self.logs,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    def to_summary_dict(self) -> Dict[str, Any]:
        issues = self.result.get("issues", []) if self.result else []
        confirmed_issues = sum(
            1 for issue in issues
            if not issue_is_dropped(issue)
        )
        return {
            "id": self.id,
            "mode": self.mode,
            "config": self.config,
            "pdf_name": self.pdf_name,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "issue_count": len(issues),
            "confirmed_issue_count": confirmed_issues,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    def to_db_row(self) -> tuple:
        return (
            self.id,
            self.mode,
            json.dumps(self.config, ensure_ascii=False),
            self.status,
            self.pdf_path,
            self.pdf_name,
            json.dumps(self.progress, ensure_ascii=False),
            json.dumps(self.logs, ensure_ascii=False),
            json.dumps(self.result, ensure_ascii=False) if self.result else None,
            self.error,
            self.created_at,
            self.started_at,
            self.completed_at,
        )

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "Task":
        config = json.loads(row["config"])
        task = cls(
            task_id=row["id"],
            mode=row["mode"],
            config=config,
            pdf_path=row["pdf_path"],
            pdf_name=row["pdf_name"],
        )
        task.status = row["status"]
        task.progress = json.loads(row["progress"])
        task.logs = json.loads(row["logs"])
        task.pdf_path = normalize_runtime_path(task.pdf_path or "")
        task.result = normalize_runtime_value(json.loads(row["result"])) if row["result"] else None
        task.error = row["error"]
        task.created_at = row["created_at"]
        task.started_at = row["started_at"]
        task.completed_at = row["completed_at"]
        return task

    def add_log(self, agent: str, stage: str, message: str, data: Optional[Dict] = None):
        """Add a log entry."""
        self.append_log_entry(
            {
                "ts": datetime.now().isoformat(),
                "agent": agent,
                "stage": stage,
                "message": message,
                "data": data or {},
            }
        )

    @staticmethod
    def _log_signature(entry: Dict[str, Any]) -> tuple:
        client_id = entry.get("client_id")
        if client_id:
            return ("client_id", client_id)
        return (
            "content",
            entry.get("ts"),
            entry.get("agent"),
            entry.get("stage"),
            entry.get("message"),
        )

    def append_log_entry(self, entry: Dict[str, Any]) -> bool:
        """Append a normalized log entry if it is not already present."""
        normalized = {
            "ts": entry.get("ts") or entry.get("timestamp") or datetime.now().isoformat(),
            "agent": entry.get("agent", "System"),
            "stage": entry.get("stage", ""),
            "message": entry.get("message", ""),
            "data": entry.get("data") or {},
        }
        if entry.get("client_id"):
            normalized["client_id"] = entry["client_id"]

        signature = self._log_signature(normalized)
        for existing in self.logs:
            if self._log_signature(existing) == signature:
                existing_data = existing.get("data")
                if not isinstance(existing_data, dict):
                    existing_data = {}
                    existing["data"] = existing_data
                for key, value in normalized.get("data", {}).items():
                    if value in (None, "", [], {}):
                        continue
                    existing_data[key] = value
                for key in ("ts", "agent", "stage", "message", "client_id"):
                    if normalized.get(key) and not existing.get(key):
                        existing[key] = normalized[key]
                return False

        self.logs.append(normalized)
        return True

    def update_progress(self, phase: str, percent: int, message: str, **kwargs):
        """Update the progress."""
        next_progress = dict(DEFAULT_PROGRESS)
        next_progress.update(self.progress or {})
        next_progress.update({
            "phase": phase,
            "percent": percent,
            "message": message,
        })
        next_progress.update(kwargs)
        self.progress = next_progress

    def save(self):
        """Save task to database."""
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO tasks
                (id, mode, config, status, pdf_path, pdf_name, progress, logs, result, error, created_at, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, self.to_db_row())
            conn.commit()
        finally:
            conn.close()


class TaskManager:
    """Manages tasks with SQLite persistence."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    init_db()
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._executor = ThreadPoolExecutor(max_workers=1)  # One task at a time
        self._callbacks: Dict[str, Callable] = {}  # task_id -> callback
        self._cancel_events: Dict[str, threading.Event] = {}
        self._recover_interrupted_tasks()
        self._initialized = True

    def create_task(
        self,
        mode: str,
        config: Dict[str, Any],
        pdf_path: str,
        pdf_name: str,
    ) -> Task:
        """Create a new task."""
        task_id = str(uuid.uuid4())[:8]
        task = Task(task_id, mode, config, pdf_path, pdf_name)
        task.save()
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        if row:
            task = Task.from_db_row(row)
            logs_dir = str(task.result.get("logs_dir", "")) if isinstance(task.result, dict) else ""
            if logs_dir:
                task.logs = self._merge_log_entries(task.logs, self._load_session_logs(logs_dir))
            return task
        return None

    def get_all_tasks(self) -> List[Task]:
        """Get all tasks."""
        conn = get_db_connection()
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        conn.close()
        return [Task.from_db_row(row) for row in rows]

    def get_active_tasks(self) -> List[Task]:
        """Get tasks that are queued or running."""
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status IN ('pending', 'running', 'cancelling')
            ORDER BY created_at ASC
            """
        ).fetchall()
        conn.close()
        return [Task.from_db_row(row) for row in rows]

    def get_active_task(self) -> Optional[Task]:
        """Return the current active task if one exists."""
        active_tasks = self.get_active_tasks()
        return active_tasks[0] if active_tasks else None

    @staticmethod
    def _normalize_chunk_ids(value: Any) -> List[int]:
        if not isinstance(value, list):
            return []
        chunk_ids: List[int] = []
        seen = set()
        for item in value:
            try:
                chunk_id = int(item)
            except (TypeError, ValueError):
                continue
            if chunk_id < 0 or chunk_id in seen:
                continue
            seen.add(chunk_id)
            chunk_ids.append(chunk_id)
        return sorted(chunk_ids)

    @classmethod
    def _infer_completed_chunk_ids(cls, task: Task) -> List[int]:
        if isinstance(task.result, dict):
            result_chunk_ids = cls._normalize_chunk_ids(task.result.get("processed_chunk_ids"))
            if result_chunk_ids:
                return result_chunk_ids

        completed = set()
        for entry in task.logs:
            if not isinstance(entry, dict):
                continue
            data = entry.get("data") or {}
            try:
                chunk_id = int(data.get("chunk_id"))
            except (TypeError, ValueError):
                continue

            stage = str(entry.get("stage", "") or "").strip().lower()
            agent = str(entry.get("agent", "") or "").strip().lower()
            if agent == "main" and stage == "chunk_complete":
                completed.add(chunk_id)
        return sorted(completed)

    @classmethod
    def build_resume_state(cls, task: Task) -> Dict[str, Any]:
        result = task.result if isinstance(task.result, dict) else {}
        issues = result.get("issues", [])
        return {
            "completed_chunk_ids": cls._infer_completed_chunk_ids(task),
            "total_chunks": int(result.get("total_chunks") or task.progress.get("total_chunks", 0) or 0),
            "issues": deepcopy(issues) if isinstance(issues, list) else [],
        }

    def prepare_task_for_resume(self, task_id: str, resume_state: Optional[Dict[str, Any]] = None) -> Optional[Task]:
        task = self.get_task(task_id)
        if not task:
            return None

        resume_state = resume_state if isinstance(resume_state, dict) else {}
        completed_chunk_ids = self._normalize_chunk_ids(resume_state.get("completed_chunk_ids"))
        total_chunks = int(resume_state.get("total_chunks") or task.progress.get("total_chunks", 0) or 0)
        task.status = "pending"
        task.error = None
        task.started_at = None
        task.completed_at = None
        task.update_progress(
            "Queued",
            max(1, int(task.progress.get("percent", 0) or 1)),
            "Resume queued from previous progress",
            current_chunk=len(completed_chunk_ids),
            total_chunks=total_chunks,
        )
        task.add_log(
            "System",
            "task_resume_requested",
            "Resume requested",
            {
                "completed_chunk_ids": completed_chunk_ids,
                "total_chunks": total_chunks,
            },
        )
        task.save()
        return task

    def _recover_interrupted_tasks(self):
        """Mark stale in-flight tasks as failed after a server restart."""
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status IN ('pending', 'running', 'cancelling')
                """
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return

        recovery_time = datetime.now().isoformat()
        for row in rows:
            task = Task.from_db_row(row)
            task.status = "failed"
            task.error = "Task interrupted by server restart"
            task.completed_at = recovery_time
            task.update_progress("Interrupted", 100, "Task interrupted by server restart")
            task.add_log("System", "task_interrupted", "Task interrupted by server restart")
            task.save()

    def is_cancel_requested(self, task_id: str) -> bool:
        cancel_event = self._cancel_events.get(task_id)
        if cancel_event and cancel_event.is_set():
            return True
        task = self.get_task(task_id)
        return bool(task and task.status in {"cancelling", "cancelled"})

    def _raise_if_cancelled(self, task_id: str) -> None:
        if self.is_cancel_requested(task_id):
            raise TaskCancelled("Task cancelled by user")

    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Request cancellation for a queued or running task."""
        task = self.get_task(task_id)
        if not task:
            return None

        if task.status in {"completed", "failed", "cancelled"}:
            return task

        cancel_event = self._cancel_events.setdefault(task_id, threading.Event())
        cancel_event.set()

        if task.status == "pending":
            task.status = "cancelled"
            task.completed_at = datetime.now().isoformat()
            task.update_progress("Cancelled", 100, "Task cancelled")
            task.add_log("System", "task_cancelled", "Task cancelled")
        else:
            task.status = "cancelling"
            task.update_progress("Cancelling", int(task.progress.get("percent", 0) or 0), "Cancelling task...")
            task.add_log("System", "task_cancelling", "Cancellation requested")
        task.save()
        return task

    @staticmethod
    def _load_session_logs(logs_dir: str) -> List[Dict[str, Any]]:
        if not logs_dir:
            return []

        normalized_logs_dir = Path(normalize_runtime_path(logs_dir))
        index_path = normalized_logs_dir / "log_index.json"
        if not index_path.exists():
            return []

        try:
            with open(index_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except (OSError, json.JSONDecodeError):
            return []

        session_id = str(payload.get("session_id", "session") or "session")
        file_map = {path.name: path for path in normalized_logs_dir.rglob("*.json")}
        logs: List[Dict[str, Any]] = []
        for entry in payload.get("logs", []):
            if not isinstance(entry, dict):
                continue
            raw_payload: Dict[str, Any] = {}
            filename = str(entry.get("filename", "") or "")
            source_path = file_map.get(filename)
            if source_path and source_path.exists():
                try:
                    with open(source_path, "r", encoding="utf-8") as file_handle:
                        raw_payload = json.load(file_handle)
                except (OSError, json.JSONDecodeError):
                    raw_payload = {}

            data = AgentLogger.extract_display_data(
                data={
                    "step": entry.get("step"),
                    "chunk_id": entry.get("chunk_id"),
                    "status": entry.get("status"),
                    "summary": entry.get("summary"),
                    "filename": filename,
                },
                input_data=raw_payload.get("input") if isinstance(raw_payload, dict) else None,
                output_data=raw_payload.get("output") if isinstance(raw_payload, dict) else None,
                message=entry.get("message", "") or entry.get("summary", "") or entry.get("stage", ""),
            )
            logs.append(
                {
                    "client_id": f"{session_id}-{int(entry.get('step', len(logs) + 1)):04d}",
                    "ts": entry.get("timestamp"),
                    "agent": entry.get("agent", "System"),
                    "stage": entry.get("stage", ""),
                    "message": entry.get("message", "") or entry.get("summary", "") or entry.get("stage", ""),
                    "data": data,
                }
            )
        return logs

    @staticmethod
    def _is_runtime_shutdown_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        return "interpreter shutdown" in text or "cannot schedule new futures after interpreter shutdown" in text

    @classmethod
    def _format_task_error_message(cls, exc: Exception) -> str:
        if cls._is_runtime_shutdown_error(exc):
            return "Task interrupted because the DraftClaw server was reloading or shutting down. Open the task and use Resume."
        return str(exc)

    @staticmethod
    def _merge_log_entries(existing_logs: List[Dict[str, Any]], incoming_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged_task = Task("merge", "merge", {})
        for entry in existing_logs:
            merged_task.append_log_entry(entry)
        for entry in incoming_logs:
            merged_task.append_log_entry(entry)
        return merged_task.logs

    @staticmethod
    def _is_cleanup_target(path: Path) -> bool:
        resolved = path.resolve()
        allowed_roots = [
            WEB_TASKS_DIR.resolve(),
            CACHE_DIR.resolve(),
            LOGS_DIR.resolve(),
        ]
        return any(resolved == root or root in resolved.parents for root in allowed_roots)

    @classmethod
    def _collect_cleanup_paths(cls, value: Any, collected: Optional[set] = None) -> set:
        paths = collected or set()
        if isinstance(value, dict):
            for nested in value.values():
                cls._collect_cleanup_paths(nested, paths)
            return paths
        if isinstance(value, list):
            for nested in value:
                cls._collect_cleanup_paths(nested, paths)
            return paths
        if isinstance(value, str):
            candidate = Path(value)
            if candidate.exists() and cls._is_cleanup_target(candidate):
                paths.add(candidate.resolve())
        return paths

    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        task = self.get_task(task_id)
        if not task:
            return False

        cleanup_paths = set()
        if task.pdf_path:
            pdf_path = Path(normalize_runtime_path(task.pdf_path))
            if pdf_path.exists() and self._is_cleanup_target(pdf_path):
                cleanup_paths.add(pdf_path.resolve())
            cache_dir = CACHE_DIR / f"{pdf_path.stem}_files"
            if cache_dir.exists() and self._is_cleanup_target(cache_dir):
                cleanup_paths.add(cache_dir.resolve())
        if isinstance(task.result, dict):
            cleanup_paths |= self._collect_cleanup_paths(task.result)

        for path in sorted(cleanup_paths, key=lambda item: (len(item.parts), str(item)), reverse=True):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()
            except OSError:
                continue

        # Delete from DB
        conn = get_db_connection()
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        return True

    def add_callback(self, task_id: str, callback: Callable):
        """Add a progress callback for SSE."""
        self._callbacks[task_id] = callback

    def remove_callback(self, task_id: str):
        """Remove a progress callback."""
        self._callbacks.pop(task_id, None)

    def run_task(
        self,
        task_id: str,
        progress_callback: Optional[Callable] = None,
        resume_state: Optional[Dict[str, Any]] = None,
    ):
        """Run a task in a background thread."""
        task = self.get_task(task_id)
        if not task or task.status != "pending":
            return

        resume_state = resume_state if isinstance(resume_state, dict) else {}
        completed_chunk_ids = self._normalize_chunk_ids(resume_state.get("completed_chunk_ids"))
        total_chunks = int(resume_state.get("total_chunks") or task.progress.get("total_chunks", 0) or 0)
        is_resuming = resume_state is not None
        task.status = "running"
        task.error = None
        task.started_at = datetime.now().isoformat()
        task.completed_at = None
        task.add_log(
            "System",
            "task_resumed" if is_resuming else "task_started",
            "Task resumed" if is_resuming else "Task started",
            {
                "completed_chunk_ids": completed_chunk_ids,
                "total_chunks": total_chunks,
            } if is_resuming else None,
        )
        task.update_progress(
            "Queued",
            max(1, int(task.progress.get("percent", 0) or 1)) if is_resuming else 1,
            "Resuming from previous progress" if is_resuming else "Task accepted, waiting for processing",
            current_chunk=len(completed_chunk_ids) if is_resuming else 0,
            total_chunks=total_chunks,
        )
        task.save()
        cancel_event = self._cancel_events.setdefault(task_id, threading.Event())

        def _run():
            try:
                import importlib
                import config
                import config_validator
                import main as main_module
                from agents.llm_utils import LLMRequestCancelled

                config.reload_runtime_config()
                main_module = importlib.reload(main_module)
                ReviewCancelled = main_module.ReviewCancelled
                run_review = main_module.run_review
                self._raise_if_cancelled(task_id)

                mode = config.normalize_review_mode(task.mode)
                mode_features = config.resolve_review_mode_features(mode)
                vision_enabled = mode_features["vision_enabled"]
                search_enabled = mode_features["search_enabled"]
                report_language = task.config.get("report_language", config.REPORT_LANGUAGE)

                def on_log(log_entry: Dict[str, Any]):
                    self._raise_if_cancelled(task_id)
                    current_task = self.get_task(task_id)
                    if not current_task:
                        return
                    if current_task.append_log_entry(log_entry):
                        current_task.save()

                # Update progress callback - reload task from DB each time
                def on_progress(progress: Dict, message: str):
                    self._raise_if_cancelled(task_id)
                    # Reload task to ensure fresh state
                    current_task = self.get_task(task_id)
                    if current_task:
                        phase = progress.get("phase", "")
                        percent = progress.get("percent", 0)
                        current_task.update_progress(
                            phase=phase,
                            percent=percent,
                            message=message,
                            current_chunk=progress.get("current_chunk", 0),
                            total_chunks=progress.get("total_chunks", 0),
                        )
                        current_task.save()
                        if progress_callback:
                            progress_callback(progress, message)

                def on_partial_result(partial_result: Dict[str, Any]):
                    self._raise_if_cancelled(task_id)
                    current_task = self.get_task(task_id)
                    if not current_task:
                        return
                    merged_result = dict(current_task.result or {})
                    merged_result.update(partial_result or {})
                    current_task.result = merged_result
                    current_task.save()

                def on_validation_log(agent: str, stage: str, message: str, data: Optional[Dict[str, Any]] = None):
                    self._raise_if_cancelled(task_id)
                    current_task = self.get_task(task_id)
                    if not current_task:
                        return
                    current_task.add_log(agent, stage, message, data)
                    current_task.save()

                current_task = self.get_task(task_id)
                if current_task:
                    current_task.update_progress("Config Validation", 2, "Checking runtime configuration")
                    current_task.add_log("ConfigValidator", "config_validation_start", "Checking runtime configuration")
                    current_task.save()

                validation_result = config_validator.validate_runtime_configuration(
                    log_callback=on_validation_log,
                )
                validated_message = (
                    "Configuration unchanged; skipped validation"
                    if validation_result.get("cached")
                    else "Runtime configuration validated"
                )
                current_task = self.get_task(task_id)
                if current_task:
                    current_task.update_progress("Config Validation", 4, validated_message)
                    current_task.add_log(
                        "ConfigValidator",
                        "config_validation_done",
                        validated_message,
                        {
                            "cached": bool(validation_result.get("cached")),
                            "validated_at": validation_result.get("validated_at"),
                        },
                    )
                    current_task.save()

                current_task = self.get_task(task_id)
                if current_task:
                    current_task.update_progress("PDF Parsing", 5, "Starting PDF parsing")
                    current_task.save()
                self._raise_if_cancelled(task_id)

                result = run_review(
                    task.pdf_path,
                    mode=mode,
                    report_language=report_language,
                    vision_enabled=vision_enabled,
                    search_enabled=search_enabled,
                    progress_callback=on_progress,
                    log_callback=on_log,
                    partial_result_callback=on_partial_result,
                    resume_state=resume_state,
                    cancel_check=lambda: cancel_event.is_set() or self.is_cancel_requested(task_id),
                )
                self._raise_if_cancelled(task_id)

                # Reload and update final status
                final_task = self.get_task(task_id)
                if final_task:
                    final_task.result = result
                    final_task.status = "completed"
                    final_task.completed_at = datetime.now().isoformat()
                    final_task.update_progress("Completed", 100, "Review completed")
                    session_logs = self._load_session_logs(str(result.get("logs_dir", "")))
                    if session_logs:
                        final_task.logs = self._merge_log_entries(final_task.logs, session_logs)
                    else:
                        final_task.add_log(
                            "System",
                            "task_completed",
                            "Task completed",
                            {"total_issues": result.get("total_issues", 0)},
                        )
                    final_task.save()

            except Exception as e:
                error_task = self.get_task(task_id)
                is_cancelled = (
                    isinstance(e, TaskCancelled)
                    or e.__class__.__name__ in {"ReviewCancelled", "LLMRequestCancelled"}
                    or self.is_cancel_requested(task_id)
                )
                if error_task and is_cancelled:
                    error_task.status = "cancelled"
                    error_task.error = None
                    error_task.completed_at = datetime.now().isoformat()
                    error_task.update_progress("Cancelled", 100, "Task cancelled")
                    error_task.add_log("System", "task_cancelled", "Task cancelled")
                    error_task.save()
                elif error_task:
                    error_message = self._format_task_error_message(e)
                    error_task.status = "failed"
                    error_task.error = error_message
                    error_task.completed_at = datetime.now().isoformat()
                    error_task.update_progress("Failed", 100, error_message)
                    error_task.add_log("System", "task_failed", f"Task failed: {error_message}")
                    error_task.save()
            finally:
                self._cancel_events.pop(task_id, None)

        self._executor.submit(_run)


# Initialize DB on module load
init_db()
