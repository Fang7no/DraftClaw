"""
Flask API routes for DraftClaw Web UI.
"""

import json
import os
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

from flask import Response, jsonify, request, send_file

from config import WEB_TASKS_DIR, get_runtime_config, normalize_review_mode, update_runtime_config
from issue_review import issue_is_dropped
from pdf_page_renderer import build_page_manifest, render_page_png
from pdf_annotation_exporter import export_annotated_pdf_bytes
from report_export_renderer import render_export_report_html
from web.tasks import TaskManager


def register_routes(app):
    """Register all API routes with the Flask app."""

    task_manager = TaskManager()

    @app.route("/api/tasks", methods=["GET"])
    def list_tasks():
        """List all tasks."""
        tasks = task_manager.get_all_tasks()
        return jsonify([t.to_summary_dict() for t in tasks])

    @app.route("/api/tasks/<task_id>", methods=["GET"])
    def get_task(task_id: str):
        """Get a specific task."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task.to_dict())

    @app.route("/api/tasks/<task_id>", methods=["DELETE"])
    def delete_task(task_id: str):
        """Delete a task."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if task.status in {"pending", "running"}:
            return jsonify({"error": "Active tasks cannot be deleted"}), 409
        success = task_manager.delete_task(task_id)
        if not success:
            return jsonify({"error": "Task not found"}), 404
        return jsonify({"success": True})

    @app.route("/api/tasks/<task_id>/cancel", methods=["POST"])
    def cancel_task(task_id: str):
        """Request cancellation for an active task."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if task.status not in {"pending", "running", "cancelling"}:
            return jsonify({"error": "Task is not active", "task": task.to_dict()}), 409
        cancelled_task = task_manager.cancel_task(task_id)
        if not cancelled_task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(cancelled_task.to_dict())

    @app.route("/api/tasks/<task_id>/resume", methods=["POST"])
    def resume_task(task_id: str):
        """Resume a failed or cancelled task from its saved progress."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if task.status not in {"failed", "cancelled"}:
            return jsonify({"error": "Task cannot be resumed", "task": task.to_dict()}), 409
        active_task = task_manager.get_active_task()
        if active_task and active_task.id != task_id:
            return jsonify({
                "error": "Another task is already queued or running",
                "active_task": active_task.to_summary_dict(),
            }), 409
        if not task.pdf_path or not os.path.exists(task.pdf_path):
            return jsonify({"error": "PDF not found"}), 404

        resume_state = task_manager.build_resume_state(task)
        resumed_task = task_manager.prepare_task_for_resume(task_id, resume_state=resume_state)
        if not resumed_task:
            return jsonify({"error": "Task not found"}), 404
        task_manager.run_task(task_id, resume_state=resume_state)
        response_task = task_manager.get_task(task_id) or resumed_task
        return jsonify(response_task.to_dict())

    @app.route("/api/tasks/<task_id>/stream")
    def stream_task(task_id: str):
        """SSE stream for task progress."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404

        def generate():
            last_log_count = 0
            last_progress = ""
            last_result = ""

            while True:
                task = task_manager.get_task(task_id)
                if not task:
                    yield f"event: error\ndata: {json.dumps({'message': 'Task not found'})}\n\n"
                    break

                # Emit new logs
                for log in task.logs[last_log_count:]:
                    yield f"event: log\ndata: {json.dumps(log, ensure_ascii=False)}\n\n"
                last_log_count = len(task.logs)

                # Emit progress (only if changed)
                progress_str = json.dumps(task.progress, ensure_ascii=False)
                if progress_str != last_progress:
                    yield f"event: progress\ndata: {progress_str}\n\n"
                    last_progress = progress_str

                result_str = json.dumps(task.result, ensure_ascii=False, sort_keys=True) if task.result else ""
                if result_str and result_str != last_result:
                    yield f"event: result\ndata: {result_str}\n\n"
                    last_result = result_str

                # Check completion
                if task.status == "completed":
                    issues = task.result.get("issues", []) if task.result else []
                    kept = sum(
                        1 for i in issues
                        if not issue_is_dropped(i)
                    )
                    yield f"event: complete\ndata: {json.dumps({'issues_total': len(issues), 'issues_kept': kept})}\n\n"
                    break

                if task.status == "failed":
                    yield f"event: error\ndata: {json.dumps({'message': task.error or 'Task failed'})}\n\n"
                    break

                if task.status == "cancelled":
                    yield f"event: cancelled\ndata: {json.dumps({'message': 'Task cancelled'})}\n\n"
                    break

                import time
                time.sleep(0.3)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/api/tasks/<task_id>/pdf")
    def serve_pdf(task_id: str):
        """Serve the PDF file."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if not task.pdf_path or not os.path.exists(task.pdf_path):
            return jsonify({"error": "PDF not found"}), 404
        return send_file(task.pdf_path, mimetype="application/pdf")

    @app.route("/api/tasks/<task_id>/pages")
    def get_pdf_pages(task_id: str):
        """Return rendered PDF page metadata for image-based viewing."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if not task.pdf_path or not os.path.exists(task.pdf_path):
            return jsonify({"error": "PDF not found"}), 404

        manifest = build_page_manifest(task.pdf_path)
        for page in manifest["pages"]:
            page_number = int(page["page_number"])
            page["image_url"] = f"/api/tasks/{task_id}/pages/{page_number}/image"
        return jsonify(manifest)

    @app.route("/api/tasks/<task_id>/pages/<int:page_number>/image")
    def get_pdf_page_image(task_id: str, page_number: int):
        """Serve a rendered PDF page image."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if not task.pdf_path or not os.path.exists(task.pdf_path):
            return jsonify({"error": "PDF not found"}), 404

        try:
            image_bytes = render_page_png(task.pdf_path, page_number)
        except IndexError:
            return jsonify({"error": "Page not found"}), 404

        return send_file(BytesIO(image_bytes), mimetype="image/png")

    @app.route("/api/tasks/<task_id>/report")
    def get_report(task_id: str):
        """Get the review report."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if not task.result:
            return jsonify({"error": "Report not available"}), 404
        return jsonify(task.result)

    @app.route("/api/tasks/<task_id>/report/export")
    def export_report(task_id: str):
        """Export a self-contained interactive HTML report."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if not task.result:
            return jsonify({"error": "Report not available"}), 404
        pdf_path = task.pdf_path or task.result.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"error": "PDF not found"}), 404

        html_content = render_export_report_html(task.result, pdf_path)
        download_stem = Path(task.pdf_name or task.id).stem
        download_name = f"{download_stem}_draftclaw_report.html"
        return send_file(
            BytesIO(html_content.encode("utf-8")),
            mimetype="text/html; charset=utf-8",
            as_attachment=True,
            download_name=download_name,
        )

    @app.route("/api/tasks/<task_id>/report/export-annotated-pdf")
    def export_annotated_pdf(task_id: str):
        """Export a PDF with bbox-based issue annotations."""
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if not task.result:
            return jsonify({"error": "Report not available"}), 404
        pdf_path = task.pdf_path or task.result.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"error": "PDF not found"}), 404

        pdf_bytes = export_annotated_pdf_bytes(task.result, pdf_path)
        download_stem = Path(task.pdf_name or task.id).stem
        download_name = f"{download_stem}_draftclaw_annotated.pdf"
        return send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=download_name,
        )

    @app.route("/api/upload", methods=["POST"])
    def upload():
        """Handle PDF upload and task creation."""
        active_task = task_manager.get_active_task()
        if active_task:
            return jsonify({
                "error": "Another task is already queued or running",
                "active_task": active_task.to_summary_dict(),
            }), 409

        # Check if PDF file is present
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400
        if not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "Only PDF files are supported"}), 400

        # Get configuration
        mode = normalize_review_mode(request.form.get("mode", "standard"))
        report_language = request.form.get("report_language", "zh")

        # Save PDF to web_tasks directory
        task_id = str(uuid.uuid4())[:8]
        WEB_TASKS_DIR.mkdir(parents=True, exist_ok=True)

        pdf_filename = f"{task_id}_{file.filename}"
        pdf_path = WEB_TASKS_DIR / pdf_filename
        file.save(str(pdf_path))

        # Create task
        config = {
            "report_language": report_language,
        }

        task = task_manager.create_task(
            mode=mode,
            config=config,
            pdf_path=str(pdf_path),
            pdf_name=file.filename,
        )

        # Start task in background
        task_manager.run_task(task.id)

        response_task = task_manager.get_task(task.id) or task
        payload = response_task.to_dict()
        payload["task_id"] = response_task.id
        return jsonify(payload), 202

    @app.route("/api/config", methods=["GET"])
    def get_config():
        """Get current runtime configuration."""
        return jsonify(get_runtime_config(mask_secrets=False))

    @app.route("/api/config", methods=["POST"])
    def save_config():
        """Update runtime configuration and persist it to .env."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid configuration payload"}), 400
        return jsonify(update_runtime_config(payload))

    @app.route("/api/health", methods=["GET"])
    def health():
        """Health check."""
        active_task = task_manager.get_active_task()
        return jsonify({
            "status": "ok",
            "active_task_id": active_task.id if active_task else None,
        })
