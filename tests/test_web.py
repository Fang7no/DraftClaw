from __future__ import annotations

import io
import os
from pathlib import Path
from uuid import uuid4

import pytest

from draftclaw._core.config import AppConfig, build_config, load_config
from draftclaw._core.contracts import ModeResult
from draftclaw._core.enums import ModeName
from draftclaw._runtime.pdf_versions import PdfVersionRegistry
from draftclaw._runtime.progress import PROGRESS_STAGE_ANALYZING, PROGRESS_STAGE_REPORTING, emit_progress
from draftclaw.web.app import create_app
from draftclaw.web.manager import JobManager
from draftclaw.web.models import (
    STATUS_COMPLETED,
    STATUS_INTERRUPTED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_STOPPED,
)
from draftclaw.web.store import JobStore
from draftclaw.web.worker import run_job


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_file(root: Path) -> Path:
    settings_path = root / "default.yaml"
    settings_path.write_text(
        "\n".join(
            [
                "run:",
                "  input_file: ./test_pdf/whu.pdf",
                "  mode: standard",
                "  run_name: demo_review",
                "llm:",
                "  api_key: seed-key",
                "  base_url: https://example.com/v1",
                "  model: seed-model",
                "  timeout_sec: 60.0",
                "  temperature: 0.0",
                "  top_p: 1.0",
                "  max_tokens: 4096",
                "  max_retries: 3",
                "  retry_backoff_sec: 1.5",
                "  use_json_schema: true",
                "  enable_cache: true",
                "  enable_merge_agent: true",
                "io:",
                "  working_dir: output",
                "  runs_dir: runs",
                "  output_filename_json: mode_result.json",
                "  output_filename_md: mode_result.md",
                "  output_filename_html: mode_result.html",
                "  copy_input_file: true",
                "parser:",
                "  text_fast_path: true",
                "  cache_in_process: true",
                "  cache_on_disk: true",
                "  docling_page_chunk_size: 8",
                "  pdf_parse_mode: fast",
                "  paddleocr_api_url: https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
                '  paddleocr_api_key: ""',
                "  paddleocr_api_model: PaddleOCR-VL-1.5",
                "  paddleocr_poll_interval_sec: 5.0",
                "  paddleocr_api_timeout_sec: 120.0",
                "standard:",
                "  target_chunks: 0",
                '  paragraph_separator_regex: "\\\\n\\\\s*\\\\n"',
                "logging:",
                "  level: INFO",
                "  log_file: run.log",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return settings_path


def _settings(
    *,
    api_key: str = "test-key",
    model: str = "demo-model",
    run_name: str | None = None,
    pdf_parse_mode: str = "fast",
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
    paddleocr_api_key: str = "",
    paddleocr_api_model: str = "PaddleOCR-VL-1.5",
) -> AppConfig:
    return build_config(
        {
            "run": {
                "run_name": run_name,
            },
            "llm": {
                "api_key": api_key,
                "base_url": "https://example.com/v1",
                "model": model,
            },
            "io": {
                "working_dir": "output",
            },
            "parser": {
                "pdf_parse_mode": pdf_parse_mode,
                "paddleocr_api_url": paddleocr_api_url,
                "paddleocr_api_key": paddleocr_api_key,
                "paddleocr_api_model": paddleocr_api_model,
            },
        }
    )


class FakeProcess:
    _next_pid = 2000

    def __init__(self) -> None:
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode = None

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def test_job_store_tracks_stop_retry_and_finalize() -> None:
    root = _artifact_dir("web_store")
    settings_path = _settings_file(root)
    store = JobStore(root / "jobs.sqlite3", settings_path=settings_path)
    store.save_settings(_settings(api_key="initial-key"))

    upload_dir = root / "uploads" / "job1"
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "paper.txt"
    input_path.write_text("alpha", encoding="utf-8")

    created = store.create_job(
        job_id="job1",
        mode="deep",
        input_filename="paper.txt",
        input_path=str(input_path),
        upload_dir=str(upload_dir),
        config_snapshot=_settings(),
    )

    assert created.status == STATUS_QUEUED
    assert created.to_dict()["progress"]["label"] == "\u7b49\u5f85\u5f00\u59cb"

    stopped = store.request_stop("job1")
    assert stopped.status == STATUS_STOPPED

    store.save_settings(_settings(api_key="retry-key"))
    requeued = store.requeue_job("job1", config_snapshot=store.load_settings())
    assert requeued.status == STATUS_QUEUED
    assert requeued.attempt_count == 2
    assert requeued.config_snapshot["llm"]["api_key"] == "retry-key"

    running = store.mark_running("job1", pid=4321)
    assert running.to_dict()["progress"]["label"] == "\u6587\u6863\u89e3\u6790\u4e2d"

    analyzing = store.update_progress(
        "job1",
        stage=PROGRESS_STAGE_ANALYZING,
        label="Agent\u68c0\u6d4b\u4e2d",
        detail="\u6b63\u5728\u6267\u884c Agent \u68c0\u6d4b",
        current=2,
        total=5,
    )
    assert analyzing.to_dict()["progress"]["percent"] == 48

    completed = store.finalize_job(
        "job1",
        status=STATUS_COMPLETED,
        run_dir=str(root / "run"),
        result_html_path=str(root / "run" / "final" / "mode_result.html"),
    )
    assert completed.status == STATUS_COMPLETED
    assert completed.result_html_path is not None


def test_job_manager_limits_concurrency_and_recovers_interrupted_jobs(monkeypatch) -> None:
    root = _artifact_dir("web_manager")
    settings_path = _settings_file(root)
    store = JobStore(root / "jobs.sqlite3", settings_path=settings_path)
    store.save_settings(_settings())

    for index in range(4):
        upload_dir = root / "uploads" / f"job{index}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        input_path = upload_dir / f"paper_{index}.txt"
        input_path.write_text("alpha", encoding="utf-8")
        store.create_job(
            job_id=f"job{index}",
            mode="standard",
            input_filename=input_path.name,
            input_path=str(input_path),
            upload_dir=str(upload_dir),
            config_snapshot=_settings(),
        )

    launched: dict[str, FakeProcess] = {}

    def launcher(job_id: str) -> FakeProcess:
        process = FakeProcess()
        launched[job_id] = process
        return process

    manager = JobManager(store, web_root=root, max_concurrent=3, process_launcher=launcher)
    manager._launch_queued_jobs()

    assert len(manager._running) == 3
    assert sum(1 for job in store.list_jobs() if job.status == STATUS_RUNNING) == 3
    assert store.get_job("job3").status == STATUS_QUEUED

    store.request_stop("job0")
    manager._stop_requested_processes()
    manager._reap_finished_processes()
    assert store.get_job("job0").status == STATUS_STOPPED

    store.mark_running("job3", pid=99999)
    terminated_pids: list[int] = []
    monkeypatch.setattr(JobManager, "_terminate_pid", staticmethod(lambda pid: terminated_pids.append(pid)))
    manager._recover_incomplete_jobs()

    assert 99999 in terminated_pids
    assert store.get_job("job3").status == STATUS_INTERRUPTED


def test_job_manager_preserves_worker_finalization() -> None:
    root = _artifact_dir("web_manager_finalize")
    settings_path = _settings_file(root)
    store = JobStore(root / "jobs.sqlite3", settings_path=settings_path)
    store.save_settings(_settings())

    upload_dir = root / "uploads" / "job1"
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "paper.txt"
    input_path.write_text("alpha", encoding="utf-8")
    store.create_job(
        job_id="job1",
        mode="standard",
        input_filename=input_path.name,
        input_path=str(input_path),
        upload_dir=str(upload_dir),
        config_snapshot=_settings(),
    )
    store.mark_running("job1", pid=4321)
    store.finalize_job(
        "job1",
        status=STATUS_COMPLETED,
        run_dir=str(root / "runtime" / "real_run"),
        result_html_path=str(root / "runtime" / "real_run" / "final" / "mode_result.html"),
    )

    process = FakeProcess()
    process.returncode = 0
    manager = JobManager(store, web_root=root, max_concurrent=1, process_launcher=lambda _: process)
    manager._running["job1"] = process

    manager._reap_finished_processes()

    preserved = store.get_job("job1")
    assert preserved.status == STATUS_COMPLETED
    assert preserved.result_html_path == str(root / "runtime" / "real_run" / "final" / "mode_result.html")


def test_job_manager_worker_subprocess_uses_workspace_source(monkeypatch) -> None:
    root = _artifact_dir("web_manager_env")
    settings_path = _settings_file(root)
    store = JobStore(root / "jobs.sqlite3", settings_path=settings_path)
    manager = JobManager(store, web_root=root)
    captured: dict[str, object] = {}

    class DummyProcess:
        pid = 4321

    def fake_popen(command, cwd, stdout, stderr, env):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["env"] = env
        return DummyProcess()

    monkeypatch.setattr("draftclaw.web.manager.subprocess.Popen", fake_popen)

    process = manager._spawn_worker_process("job1")

    assert process.pid == 4321
    assert captured["cwd"] == str(root.resolve())
    assert "--settings" in captured["command"]
    assert str(settings_path.resolve()) in captured["command"]
    python_path = captured["env"]["PYTHONPATH"]
    assert str((Path(__file__).resolve().parents[1] / "src").resolve()) in python_path.split(os.pathsep)


def test_web_app_routes_cover_settings_jobs_report_and_delete() -> None:
    root = _artifact_dir("web_app")
    settings_path = _settings_file(root)
    app = create_app(web_root=root, settings_path=settings_path, testing=True, auto_start_manager=False)
    client = app.test_client()
    store: JobStore = app.extensions["draftclaw.job_store"]

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "DraftClaw" in html
    assert "terminal-pagination" in html

    settings_response = client.post(
        "/api/settings",
        json={
            "llm": {
                "api_key": "updated-key",
                "base_url": "https://example.com/v1",
                "model": "demo-model",
            },
            "parser": {
                "pdf_parse_mode": "accurate",
                "paddleocr_api_url": "https://ocr.example/api/parse",
                "paddleocr_api_key": "ocr-key",
                "paddleocr_api_model": "PaddleOCR-VL-1.5",
            },
            "run": {
                "run_name": "updated-run",
            },
        },
    )
    assert settings_response.status_code == 200
    assert settings_response.json["llm"]["api_key"] == "updated-key"
    assert settings_response.json["parser"]["pdf_parse_mode"] == "accurate"
    assert settings_response.json["parser"]["paddleocr_api_url"] == "https://ocr.example/api/parse"
    assert settings_response.json["parser"]["paddleocr_api_key"] == "ocr-key"
    assert settings_response.json["parser"]["paddleocr_api_model"] == "PaddleOCR-VL-1.5"
    assert settings_response.json["run"]["run_name"] == "updated-run"
    saved_config = load_config(settings_path)
    assert saved_config.llm.api_key == "updated-key"
    assert saved_config.io.working_dir == "output"
    assert saved_config.run.input_file == "./test_pdf/whu.pdf"
    assert saved_config.run.run_name == "updated-run"
    assert saved_config.parser.pdf_parse_mode == "accurate"
    assert saved_config.parser.paddleocr_api_url == "https://ocr.example/api/parse"
    assert saved_config.parser.paddleocr_api_key == "ocr-key"
    assert saved_config.parser.paddleocr_api_model == "PaddleOCR-VL-1.5"

    upload_response = client.post(
        "/api/jobs",
        data={
            "mode": "deep",
            "files": [
                (io.BytesIO(b"alpha"), "paper_a.txt"),
                (io.BytesIO(b"beta"), "paper_b.txt"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 201
    jobs = upload_response.json["jobs"]
    assert len(jobs) == 2
    job_id = jobs[0]["job_id"]

    refresh_response = client.post(
        "/api/settings",
        json={
            "llm": {
                "api_key": "retry-key",
                "base_url": "https://example.com/v1",
                "model": "retry-model",
            }
        },
    )
    assert refresh_response.status_code == 200

    stop_response = client.post(f"/api/jobs/{job_id}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json["status"] == STATUS_STOPPED

    retry_response = client.post(f"/api/jobs/{job_id}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json["status"] == STATUS_QUEUED
    refreshed_job = store.get_job(job_id)
    assert refreshed_job.config_snapshot["llm"]["api_key"] == "retry-key"
    assert refreshed_job.config_snapshot["llm"]["model"] == "retry-model"
    assert refreshed_job.config_snapshot["parser"]["pdf_parse_mode"] == "fast"

    run_dir = root / "runtime" / refreshed_job.job_id
    report_path = run_dir / "final" / "mode_result.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    store.finalize_job(
        job_id,
        status=STATUS_COMPLETED,
        run_dir=str(run_dir.resolve()),
        result_html_path=str(report_path.resolve()),
    )

    jobs_response = client.get("/api/jobs")
    assert jobs_response.status_code == 200
    current_job = next(item for item in jobs_response.json["jobs"] if item["job_id"] == job_id)
    assert current_job["report_url"] == f"/reports/{job_id}"
    assert current_job["progress"]["percent"] == 100

    report_response = client.get(f"/reports/{job_id}")
    assert report_response.status_code == 200
    assert "ok" in report_response.get_data(as_text=True)
    report_response.close()

    delete_response = client.delete(f"/api/jobs/{job_id}")
    assert delete_response.status_code == 200
    assert not run_dir.exists()
    with pytest.raises(KeyError):
        store.get_job(job_id)


def test_web_app_rejects_job_submission_without_valid_runtime_settings() -> None:
    root = _artifact_dir("web_app_invalid_settings")
    settings_path = root / "missing.yaml"
    app = create_app(web_root=root, settings_path=settings_path, testing=True, auto_start_manager=False)
    client = app.test_client()

    response = client.post(
        "/api/jobs",
        data={
            "mode": "standard",
            "files": [(io.BytesIO(b"alpha"), "paper.txt")],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["requires_settings"] is True
    assert "API" in response.json["error"]


def test_web_app_rejects_accurate_pdf_mode_without_paddleocr_api() -> None:
    root = _artifact_dir("web_app_invalid_pdf_mode")
    settings_path = _settings_file(root)
    app = create_app(web_root=root, settings_path=settings_path, testing=True, auto_start_manager=False)
    client = app.test_client()
    store: JobStore = app.extensions["draftclaw.job_store"]
    store.save_settings(
        _settings(
            pdf_parse_mode="accurate",
            paddleocr_api_url="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
            paddleocr_api_key="",
        )
    )

    response = client.post(
        "/api/jobs",
        data={
            "mode": "standard",
            "pdf_parse_mode": "accurate",
            "files": [(io.BytesIO(b"%PDF-1.4"), "paper.pdf")],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["requires_settings"] is True
    assert "PaddleOCR Token" in response.json["error"]


def test_web_app_allows_non_pdf_submission_when_accurate_mode_is_selected() -> None:
    root = _artifact_dir("web_app_accurate_non_pdf")
    settings_path = _settings_file(root)
    app = create_app(web_root=root, settings_path=settings_path, testing=True, auto_start_manager=False)
    client = app.test_client()
    store: JobStore = app.extensions["draftclaw.job_store"]
    store.save_settings(_settings(paddleocr_api_key=""))

    response = client.post(
        "/api/jobs",
        data={
            "mode": "standard",
            "pdf_parse_mode": "accurate",
            "files": [(io.BytesIO(b"alpha"), "paper.txt")],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    job_id = response.json["jobs"][0]["job_id"]
    assert store.get_job(job_id).config_snapshot["parser"]["pdf_parse_mode"] == "accurate"


def test_web_app_retry_preserves_pdf_parse_mode_for_pdf_jobs() -> None:
    root = _artifact_dir("web_app_retry_pdf_mode")
    settings_path = _settings_file(root)
    app = create_app(web_root=root, settings_path=settings_path, testing=True, auto_start_manager=False)
    client = app.test_client()
    store: JobStore = app.extensions["draftclaw.job_store"]
    store.save_settings(
        _settings(
            pdf_parse_mode="fast",
            paddleocr_api_key="retry-ocr-key",
            paddleocr_api_url="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
        )
    )

    upload_dir = root / "uploads" / "job1"
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "paper.pdf"
    input_path.write_bytes(b"%PDF-1.4")
    store.create_job(
        job_id="job1",
        mode="standard",
        input_filename="paper.pdf",
        input_path=str(input_path),
        upload_dir=str(upload_dir),
        config_snapshot=_settings(
            pdf_parse_mode="accurate",
            paddleocr_api_key="old-ocr-key",
            paddleocr_api_url="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
        ),
    )
    store.request_stop("job1")

    response = client.post("/api/jobs/job1/retry")

    assert response.status_code == 200
    retried = store.get_job("job1")
    assert retried.config_snapshot["parser"]["pdf_parse_mode"] == "accurate"
    assert retried.config_snapshot["parser"]["paddleocr_api_key"] == "retry-ocr-key"


def test_web_app_requires_confirmation_for_changed_pdf_upload() -> None:
    root = _artifact_dir("web_pdf_confirm")
    settings_path = _settings_file(root)
    seed_dir = root / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_pdf = seed_dir / "paper.pdf"
    seed_pdf.write_bytes(b"original")
    PdfVersionRegistry(root).record(seed_pdf)

    app = create_app(web_root=root, settings_path=settings_path, testing=True, auto_start_manager=False)
    client = app.test_client()

    conflict_response = client.post(
        "/api/jobs",
        data={
            "mode": "standard",
            "files": [(io.BytesIO(b"changed"), "paper.pdf")],
        },
        content_type="multipart/form-data",
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json["requires_confirmation"] is True
    assert conflict_response.json["conflicts"][0]["filename"] == "paper.pdf"

    accepted_response = client.post(
        "/api/jobs",
        data={
            "mode": "standard",
            "confirm_reparse": "true",
            "files": [(io.BytesIO(b"changed"), "paper.pdf")],
        },
        content_type="multipart/form-data",
    )
    assert accepted_response.status_code == 201
    assert len(accepted_response.json["jobs"]) == 1


def test_web_app_preserves_pdf_bytes_after_conflict_check() -> None:
    root = _artifact_dir("web_pdf_upload_bytes")
    settings_path = _settings_file(root)
    app = create_app(web_root=root, settings_path=settings_path, testing=True, auto_start_manager=False)
    client = app.test_client()
    store: JobStore = app.extensions["draftclaw.job_store"]
    pdf_bytes = b"%PDF-1.4\\n1 0 obj\\n<<>>\\nendobj\\ntrailer\\n<<>>\\n%%EOF"

    response = client.post(
        "/api/jobs",
        data={
            "mode": "standard",
            "files": [(io.BytesIO(pdf_bytes), "paper.pdf")],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    job_id = response.json["jobs"][0]["job_id"]
    job = store.get_job(job_id)
    assert Path(job.input_path).read_bytes() == pdf_bytes


def test_worker_updates_job_completion(monkeypatch) -> None:
    root = _artifact_dir("web_worker")
    settings_path = _settings_file(root)
    store = JobStore(root / "jobs.sqlite3", settings_path=settings_path)
    store.save_settings(_settings(run_name="web_run"))

    upload_dir = root / "uploads" / "job1"
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "paper.pdf"
    input_path.write_bytes(b"alpha")
    store.create_job(
        job_id="job1",
        mode="fast",
        input_filename="paper.pdf",
        input_path=str(input_path),
        upload_dir=str(upload_dir),
        config_snapshot=_settings(run_name="web_run"),
    )
    store.mark_running("job1", pid=1234)

    run_dir = root / "output" / "runs" / "20260323" / "run_fake"
    report_path = run_dir / "final" / "mode_result.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("<html><body>worker</body></html>", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_review_sync(self, **kwargs):
        emit_progress(
            self._service._progress_callback,
            stage=PROGRESS_STAGE_ANALYZING,
            label="Agent\u68c0\u6d4b\u4e2d",
            detail="\u6b63\u5728\u6267\u884c Agent \u68c0\u6d4b",
            current=1,
            total=1,
        )
        emit_progress(
            self._service._progress_callback,
            stage=PROGRESS_STAGE_REPORTING,
            label="\u62a5\u544a\u751f\u6210\u4e2d",
            detail="\u5408\u5e76\u7ed3\u679c\u5e76\u5199\u5165\u6700\u7ec8\u62a5\u544a",
        )
        captured.update(kwargs)
        return ModeResult(mode=ModeName.FAST), run_dir

    monkeypatch.setattr("draftclaw.web.worker.DraftClawApp.review_sync", fake_review_sync)

    exit_code = run_job(
        db_path=str(store.db_path),
        job_id="job1",
        web_root=str(root),
        settings_path=str(settings_path),
    )

    assert exit_code == 0
    completed = store.get_job("job1")
    assert completed.status == STATUS_COMPLETED
    assert completed.result_html_path == str(report_path.resolve())
    assert completed.progress_stage == PROGRESS_STAGE_REPORTING
    assert captured["run_name"] == "web_run"
    status = PdfVersionRegistry(root).inspect(input_path)
    assert status.previous_sha256 == status.sha256


def test_worker_uses_current_settings_when_job_snapshot_is_redacted(monkeypatch) -> None:
    root = _artifact_dir("web_worker_redacted")
    settings_path = _settings_file(root)
    store = JobStore(root / "jobs.sqlite3", settings_path=settings_path)
    store.save_settings(_settings(api_key="live-key", run_name="live_run"))

    upload_dir = root / "uploads" / "job1"
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "paper.pdf"
    input_path.write_bytes(b"alpha")
    store.create_job(
        job_id="job1",
        mode="fast",
        input_filename="paper.pdf",
        input_path=str(input_path),
        upload_dir=str(upload_dir),
        config_snapshot=_settings(api_key="***", run_name="masked_run"),
    )
    store.mark_running("job1", pid=1234)

    run_dir = root / "output" / "runs" / "20260327" / "run_live"
    report_path = run_dir / "final" / "mode_result.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("<html><body>worker</body></html>", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_review_sync(self, **kwargs):
        captured["api_key"] = self.config.llm.api_key
        captured["run_name"] = kwargs["run_name"]
        return ModeResult(mode=ModeName.FAST), run_dir

    monkeypatch.setattr("draftclaw.web.worker.DraftClawApp.review_sync", fake_review_sync)

    exit_code = run_job(
        db_path=str(store.db_path),
        job_id="job1",
        web_root=str(root),
        settings_path=str(settings_path),
    )

    assert exit_code == 0
    assert captured["api_key"] == "live-key"
    assert captured["run_name"] == "live_run"
    assert store.get_job("job1").status == STATUS_COMPLETED


def test_worker_uses_current_parser_settings_when_job_snapshot_has_masked_ocr_key(monkeypatch) -> None:
    root = _artifact_dir("web_worker_parser_redacted")
    settings_path = _settings_file(root)
    store = JobStore(root / "jobs.sqlite3", settings_path=settings_path)
    store.save_settings(
        _settings(
            api_key="live-key",
            run_name="accurate_run",
            pdf_parse_mode="accurate",
            paddleocr_api_url="https://ocr.example/api/parse",
            paddleocr_api_key="live-ocr-key",
        )
    )

    upload_dir = root / "uploads" / "job1"
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "paper.pdf"
    input_path.write_bytes(b"alpha")
    store.create_job(
        job_id="job1",
        mode="fast",
        input_filename="paper.pdf",
        input_path=str(input_path),
        upload_dir=str(upload_dir),
        config_snapshot=_settings(
            api_key="live-key",
            run_name="masked_run",
            pdf_parse_mode="accurate",
            paddleocr_api_url="https://ocr.example/api/parse",
            paddleocr_api_key="***",
        ),
    )
    store.mark_running("job1", pid=1234)

    run_dir = root / "output" / "runs" / "20260327" / "run_accurate"
    report_path = run_dir / "final" / "mode_result.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("<html><body>worker</body></html>", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_review_sync(self, **kwargs):
        captured["ocr_key"] = self.config.parser.paddleocr_api_key
        captured["run_name"] = kwargs["run_name"]
        return ModeResult(mode=ModeName.FAST), run_dir

    monkeypatch.setattr("draftclaw.web.worker.DraftClawApp.review_sync", fake_review_sync)

    exit_code = run_job(
        db_path=str(store.db_path),
        job_id="job1",
        web_root=str(root),
        settings_path=str(settings_path),
    )

    assert exit_code == 0
    assert captured["ocr_key"] == "live-ocr-key"
    assert captured["run_name"] == "accurate_run"
    assert store.get_job("job1").status == STATUS_COMPLETED
