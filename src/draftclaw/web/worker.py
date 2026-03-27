from __future__ import annotations

import argparse
import sys
from pathlib import Path

from draftclaw._core.runtime_validation import runtime_settings_error
from draftclaw._core.enums import ModeName
from draftclaw._runtime.progress import ProgressCallback, ProgressEvent, emit_progress
from draftclaw.app import DraftClawApp
from draftclaw.web.store import JobStore


def run_job(
    *,
    db_path: str,
    job_id: str,
    web_root: str,
    settings_path: str,
) -> int:
    store = JobStore(db_path, settings_path=settings_path)
    job = store.get_job(job_id)
    web_root_path = Path(web_root).resolve()
    run_dir = web_root_path / "runtime" / job_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Build AppConfig from job's config_snapshot
    from draftclaw._core.config import build_config
    config = build_config(job.config_snapshot)
    settings_error = runtime_settings_error(config, input_path=job.input_path)
    if settings_error is not None:
        current_config = store.load_settings()
        current_settings_error = runtime_settings_error(
            current_config,
            effective_pdf_parse_mode=config.parser.pdf_parse_mode,
            input_path=job.input_path,
        )
        if current_settings_error is None:
            config = current_config.model_copy(
                update={
                    "parser": current_config.parser.model_copy(
                        update={"pdf_parse_mode": config.parser.pdf_parse_mode},
                        deep=True,
                    )
                },
                deep=True,
            )
        else:
            store.finalize_job(
                job_id,
                status="interrupted",
                run_dir=str(run_dir),
                result_html_path="",
                error_detail=current_settings_error,
            )
            return 1

    # Progress callback that updates the store
    def progress_callback(event: ProgressEvent) -> None:
        store.update_progress(
            job_id,
            stage=event.stage,
            label=event.label,
            detail=event.detail,
            current=event.current,
            total=event.total,
        )

    app = DraftClawApp(
        config=config,
        working_dir=run_dir,
        progress_callback=progress_callback,
    )

    try:
        result, result_path = app.review_sync(
            input_path=job.input_path,
            mode=ModeName(job.mode),
            run_name=config.run.run_name,
        )

        # Record the PDF version after successful processing
        from draftclaw._runtime.pdf_versions import PdfVersionRegistry
        PdfVersionRegistry(web_root_path).record(job.input_path)

        # result_path is the run directory; HTML is at result_path / "final" / "mode_result.html"
        html_path = result_path / "final" / "mode_result.html"
        store.finalize_job(
            job_id,
            status="completed",
            run_dir=str(result_path),
            result_html_path=str(html_path) if html_path.exists() else "",
        )
        return 0
    except Exception as exc:
        store.finalize_job(
            job_id,
            status="interrupted",
            run_dir=str(run_dir),
            result_html_path="",
            error_detail=f"\u4efb\u52a1\u5904\u7406\u5931\u8d25\uff1a{exc}",
        )
        return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--web-root", required=True)
    parser.add_argument("--db", dest="db_path", required=False)
    args = parser.parse_args()

    settings_path = Path(args.settings).resolve()
    web_root = Path(args.web_root).resolve()
    job_id = args.job_id

    # Derive db_path from web_root / jobs.sqlite3
    db_path = str(web_root / "jobs.sqlite3")

    exit_code = run_job(
        db_path=db_path,
        job_id=job_id,
        web_root=str(web_root),
        settings_path=str(settings_path),
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
