from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from draftclaw._core.config import build_config, load_config
from draftclaw._core.runtime_validation import runtime_settings_error
from draftclaw._runtime.pdf_versions import PdfVersionRegistry
from draftclaw.web.manager import JobManager
from draftclaw.web.models import STATUS_COMPLETED, STATUS_QUEUED, Job
from draftclaw.web.store import JobStore

_LEGACY_INDEX_MARKERS = (
    "<div id='app'></div>",
    "<div class='terminal-pagination'></div>",
)


def _rewind_uploaded_file(upload: Any) -> None:
    for candidate in (upload, getattr(upload, "stream", None)):
        if candidate is None or not hasattr(candidate, "seek"):
            continue
        try:
            candidate.seek(0)
            return
        except Exception:
            continue


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge override into base, returning a new dict."""
    from enum import Enum

    def _convert(obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(item) for item in obj]
        return obj

    result = dict(_convert(base))
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = _convert(value)
    return result


def _with_pdf_parse_mode(config, pdf_parse_mode: str):
    snapshot = config.model_dump(mode="python")
    snapshot.setdefault("parser", {})
    snapshot["parser"]["pdf_parse_mode"] = str(pdf_parse_mode or "fast").strip().lower() or "fast"
    return build_config(snapshot)


def _package_web_resource(*parts: str):
    resource = files("draftclaw")
    for part in ("web", *parts):
        resource = resource.joinpath(part)
    return resource


def _read_text_resource(*parts: str) -> str:
    return _package_web_resource(*parts).read_text(encoding="utf-8")


def _should_refresh_index(index_path: Path) -> bool:
    if not index_path.exists():
        return True

    try:
        content = index_path.read_text(encoding="utf-8")
    except OSError:
        return False

    stripped = content.strip()
    if not stripped:
        return True
    if "dashboard-shell" in stripped and "/static/app.js" in stripped:
        return False
    return all(marker in stripped for marker in _LEGACY_INDEX_MARKERS)


def _seed_web_root(web_root: Path) -> Path:
    index_path = web_root / "index.html"
    if _should_refresh_index(index_path):
        index_path.write_text(_read_text_resource("templates", "dashboard.html"), encoding="utf-8")

    static_root = web_root / "static"
    static_root.mkdir(parents=True, exist_ok=True)
    for asset_name in ("app.css", "app.js"):
        asset_path = static_root / asset_name
        if asset_path.exists():
            continue
        asset_path.write_text(_read_text_resource("static", asset_name), encoding="utf-8")

    return index_path


def create_app(
    *,
    web_root: str | Path,
    settings_path: str | Path | None = None,
    testing: bool = False,
    auto_start_manager: bool = False,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["TESTING"] = testing

    web_root = Path(web_root).resolve()
    web_root.mkdir(parents=True, exist_ok=True)
    _seed_web_root(web_root)

    if settings_path:
        settings_path = Path(settings_path).resolve()
    else:
        settings_path = web_root / "default.yaml"

    db_path = web_root / "jobs.sqlite3"
    store = JobStore(db_path, settings_path=settings_path)

    manager: JobManager | None = None
    if auto_start_manager:
        manager = JobManager(store, web_root=web_root, max_concurrent=3)
        manager.start()

    @app.route("/")
    def index() -> Any:
        return app.response_class(_read_text_resource("templates", "dashboard.html"), mimetype="text/html")

    @app.route("/static/<path:asset_path>")
    def static_asset(asset_path: str) -> Any:
        if asset_path == "app.css":
            return app.response_class(_read_text_resource("static", "app.css"), mimetype="text/css")
        if asset_path == "app.js":
            return app.response_class(
                _read_text_resource("static", "app.js"),
                mimetype="application/javascript",
            )
        candidate = web_root / "static" / asset_path
        if not candidate.exists():
            abort(404)
        return send_from_directory(str(web_root / "static"), asset_path)

    @app.route("/api/settings", methods=["GET"])
    def get_settings() -> Any:
        try:
            cfg = store.load_settings()
            return jsonify(cfg.model_dump())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/settings", methods=["POST"])
    def post_settings() -> Any:
        try:
            data = request.get_json()
            if settings_path:
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                # Merge with existing config to preserve unspecified fields
                try:
                    existing = load_config(settings_path).model_dump()
                except Exception:
                    existing = {}
                # Deep merge: POST data overrides existing
                merged = _deep_merge(existing, data)
                cfg = build_config(merged)
                with open(settings_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(cfg.model_dump(mode="json"), f, allow_unicode=True)
            else:
                cfg = build_config(data)
            store.save_settings(cfg)
            return jsonify(cfg.model_dump(mode="json"))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs", methods=["GET"])
    def get_jobs() -> Any:
        jobs = store.list_jobs()
        return jsonify({"jobs": [j.to_dict() for j in jobs]})

    @app.route("/api/jobs", methods=["POST"])
    def post_jobs() -> Any:
        from uuid import uuid4

        mode = request.form.get("mode", "standard")
        pdf_parse_mode = request.form.get("pdf_parse_mode", "fast")
        confirm_reparse = request.form.get("confirm_reparse")
        files = request.files.getlist("files")

        if not files:
            return jsonify({"error": "No files uploaded"}), 400

        try:
            cfg = store.load_settings()
        except Exception:
            cfg = build_config({})

        has_pdf_upload = any((f.filename or "").lower().endswith(".pdf") for f in files)
        runtime_config = _with_pdf_parse_mode(cfg, pdf_parse_mode)
        settings_error = runtime_settings_error(
            runtime_config,
            effective_pdf_parse_mode=pdf_parse_mode,
            requires_pdf_support=has_pdf_upload,
        )
        if settings_error is not None:
            return jsonify({"error": settings_error, "requires_settings": True}), 400

        # Check for PDF conflicts
        conflicts = []
        if not confirm_reparse:
            registry = PdfVersionRegistry(web_root)
            for f in files:
                if f.filename and f.filename.lower().endswith(".pdf"):
                    temp_path = web_root / ".uploads" / f.filename
                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                    f.save(str(temp_path))
                    status = registry.inspect(temp_path)
                    if status.changed:
                        conflicts.append({"filename": f.filename, "status": status})
                    temp_path.unlink(missing_ok=True)
                    _rewind_uploaded_file(f)

            if conflicts:
                return jsonify({
                    "requires_confirmation": True,
                    "conflicts": [{"filename": c["filename"]} for c in conflicts],
                }), 409

        # Save settings snapshot if not already saved
        try:
            store.save_settings(cfg)
        except Exception:
            store.save_settings({})

        created_jobs = []
        for f in files:
            job_id = uuid4().hex[:12]
            upload_dir = web_root / "uploads" / job_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            input_path = upload_dir / f.filename
            f.save(str(input_path))
            job_config = _with_pdf_parse_mode(cfg, pdf_parse_mode)
            runtime_snapshot = job_config.snapshot(redact_secrets=False)

            job = store.create_job(
                job_id=job_id,
                mode=mode,
                input_filename=f.filename or "unknown",
                input_path=str(input_path),
                upload_dir=str(upload_dir),
                config_snapshot=runtime_snapshot,
            )
            created_jobs.append(job)

        return jsonify({"jobs": [j.to_dict() for j in created_jobs]}), 201

    @app.route("/api/jobs/<job_id>/stop", methods=["POST"])
    def post_stop(job_id: str) -> Any:
        try:
            job = store.request_stop(job_id)
            return jsonify(job.to_dict())
        except KeyError:
            return jsonify({"error": "Job not found"}), 404

    @app.route("/api/jobs/<job_id>/retry", methods=["POST"])
    def post_retry(job_id: str) -> Any:
        try:
            current_job = store.get_job(job_id)
            cfg = store.load_settings()
            job_parse_mode = current_job.config_snapshot.get("parser", {}).get("pdf_parse_mode", "fast")
            retry_config = _with_pdf_parse_mode(cfg, job_parse_mode)
            settings_error = runtime_settings_error(
                retry_config,
                effective_pdf_parse_mode=job_parse_mode,
                input_path=current_job.input_path,
            )
            if settings_error is not None:
                return jsonify({"error": settings_error, "requires_settings": True}), 400
            job = store.requeue_job(job_id, retry_config)
            return jsonify(job.to_dict())
        except KeyError:
            return jsonify({"error": "Job not found"}), 404

    @app.route("/api/jobs/<job_id>", methods=["DELETE"])
    def delete_job(job_id: str) -> Any:
        try:
            job = store.get_job(job_id)
            # Remove run directory
            if job.run_dir:
                run_path = Path(job.run_dir)
                if run_path.exists():
                    shutil.rmtree(run_path)
            # Remove upload directory
            if job.upload_dir:
                upload_path = Path(job.upload_dir)
                if upload_path.exists():
                    shutil.rmtree(upload_path)
            # Remove from store (mark as deleted by removing from jobs table)
            store.delete_job(job_id)
            return jsonify({"deleted": job_id})
        except KeyError:
            return jsonify({"error": "Job not found"}), 404

    @app.route("/reports/<job_id>")
    def get_report(job_id: str) -> Any:
        try:
            job = store.get_job(job_id)
            if not job.result_html_path:
                return jsonify({"error": "Report not available"}), 404
            report_path = Path(job.result_html_path)
            if not report_path.exists():
                return jsonify({"error": "Report file not found"}), 404
            return send_file(report_path)
        except KeyError:
            return jsonify({"error": "Job not found"}), 404

    app.extensions["draftclaw.job_store"] = store  # type: ignore[attr-defined]
    app.extensions["draftclaw.manager"] = manager  # type: ignore[attr-defined]

    return app
