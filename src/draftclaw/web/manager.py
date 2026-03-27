from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from draftclaw.web.models import STATUS_COMPLETED, STATUS_INTERRUPTED, STATUS_QUEUED, STATUS_RUNNING, STATUS_STOPPED, Job
from draftclaw.web.store import JobStore


class JobManager:
    def __init__(
        self,
        store: JobStore,
        web_root: str | Path,
        *,
        max_concurrent: int = 3,
        process_launcher: Callable[[str], Any] | None = None,
    ) -> None:
        self._store = store
        self._web_root = Path(web_root).resolve()
        self._max_concurrent = max_concurrent
        self._process_launcher = process_launcher or self._default_launcher
        self._running: dict[str, Any] = {}
        self._stopping: set[str] = set()

    def _default_launcher(self, job_id: str) -> subprocess.Popen:
        # Find project src root relative to this file
        # draftclaw/web/manager.py -> parents[0]=web, [1]=draftclaw, [2]=src
        # project root = parents[3]
        project_root = Path(__file__).resolve().parents[3]
        src_root = str(project_root / "src")
        env = dict(os.environ)
        pythonpath = env.get("PYTHONPATH", "")
        # Avoid duplicating paths already in PYTHONPATH
        if src_root not in pythonpath.split(os.pathsep):
            env["PYTHONPATH"] = src_root if not pythonpath else f"{src_root}{os.pathsep}{pythonpath}"

        return subprocess.Popen(
            [
                sys.executable, "-m", "draftclaw.web.worker",
                "--settings", str(self._store.settings_path),
                "--job-id", job_id,
                "--web-root", str(self._web_root),
            ],
            cwd=str(self._web_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def _launch_queued_jobs(self) -> None:
        for job in self._store.list_jobs():
            if job.status != STATUS_QUEUED:
                continue
            if len(self._running) >= self._max_concurrent:
                break
            self._spawn_worker_process(job.job_id)

    def _spawn_worker_process(self, job_id: str) -> Any:
        try:
            job = self._store.get_job(job_id)
        except KeyError:
            job = None
        if job is not None and job.status != STATUS_QUEUED:
            return None
        process = self._process_launcher(job_id)
        if job is not None:
            self._running[job_id] = process
            parsing_label = "\u6587\u6863\u89e3\u6790\u4e2d"
            if job.input_filename.lower().endswith(".pdf"):
                parsing_label = "PDF\u89e3\u6790\u4e2d"
            self._store.mark_running(
                job_id,
                pid=process.pid,
                label=parsing_label,
                detail="\u6b63\u5728\u8bfb\u53d6\u6b63\u6587\u4e0e\u7ed3\u6784\u4fe1\u606f",
            )
        return process

    def _stop_requested_processes(self) -> None:
        for job in self._store.list_jobs():
            if job.status != STATUS_STOPPED:
                continue
            proc = self._running.get(job.job_id)
            if proc is not None:
                self._stopping.add(job.job_id)
                try:
                    proc.kill()
                except Exception:
                    pass

    def _reap_finished_processes(self) -> None:
        finished = []
        for job_id, proc in list(self._running.items()):
            returncode = proc.poll()
            if returncode is not None:
                finished.append(job_id)
                try:
                    job = self._store.get_job(job_id)
                except KeyError:
                    job = None
                if job_id in self._stopping:
                    if job is not None and job.status != STATUS_STOPPED:
                        self._store.request_stop(job_id)
                elif job is not None and job.status == STATUS_RUNNING:
                    self._store.finalize_job(
                        job_id,
                        status=STATUS_COMPLETED if returncode == 0 else STATUS_INTERRUPTED,
                        run_dir=str(self._web_root / "runtime" / job_id),
                        result_html_path="",
                        error_detail=None if returncode == 0 else "\u5b50\u8fdb\u7a0b\u63d0\u524d\u9000\u51fa\uff0c\u8bf7\u68c0\u67e5\u914d\u7f6e\u6216\u91cd\u8bd5\u3002",
                    )
        for job_id in finished:
            del self._running[job_id]
            self._stopping.discard(job_id)

    def _recover_incomplete_jobs(self) -> None:
        for job in self._store.list_jobs():
            if job.status == STATUS_RUNNING and job.pid is not None:
                self._terminate_pid(job.pid)
                self._store.finalize_job(
                    job.job_id,
                    status=STATUS_INTERRUPTED,
                    run_dir=str(self._web_root / "runtime" / job.job_id),
                    result_html_path="",
                )

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, PermissionError):
            pass

    def _poll_loop(self) -> None:
        while True:
            self._launch_queued_jobs()
            self._stop_requested_processes()
            self._reap_finished_processes()
            time.sleep(1.0)

    def start(self) -> None:
        self._recover_incomplete_jobs()
        thread = threading.Thread(target=self._poll_loop, daemon=True)
        thread.start()
