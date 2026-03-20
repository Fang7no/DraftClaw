from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from draftclaw._core.contracts import CheckItem, ChunkInfo, DocumentText, ErrorItem, ModeResult, RunRecord
from draftclaw._history.trace import RunPaths
from draftclaw._postprocess.finalize import prepare_mode_result, render_html_report, render_markdown_summary


class HistoryStore:
    def __init__(self, run_paths: RunPaths) -> None:
        self.paths = run_paths

    def save_input_file(self, source_path: str, suffix: str) -> Path:
        src = Path(source_path)
        dst = self.paths.input / f"source_copy{suffix}"
        shutil.copyfile(src, dst)
        return dst

    def save_document_manifest(self, document: DocumentText) -> Path:
        path = self.paths.meta / "document.json"
        path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_preprocess_text(self, text: str) -> Path:
        path = self.paths.preprocess / "full_text.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def save_chunks(self, chunks: list[str], infos: list[ChunkInfo]) -> list[Path]:
        saved: list[Path] = []
        for idx, chunk in enumerate(chunks, start=1):
            path = self.paths.chunks / f"chunk_{idx}.txt"
            path.write_text(chunk, encoding="utf-8")
            saved.append(path)
        manifest = self.paths.chunks / "chunk_manifest.json"
        manifest.write_text(
            json.dumps([info.model_dump(mode="json") for info in infos], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return saved

    def save_prompt(self, stage: str, round_no: int, content: str) -> Path:
        path = self.paths.prompts / f"{stage}_{round_no}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def save_raw_response(self, stage: str, round_no: int, content: str) -> Path:
        path = self.paths.responses_raw / f"{stage}_{round_no}.txt"
        path.write_text(content, encoding="utf-8")
        return path

    def save_parsed_response(self, stage: str, round_no: int, data: dict[str, Any]) -> Path:
        path = self.paths.responses_parsed / f"{stage}_{round_no}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_state(self, round_no: int | str, checklist: list[CheckItem], errorlist: list[ErrorItem]) -> tuple[Path, Path]:
        tag = str(round_no)
        check_path = self.paths.state / f"checklist_round_{tag}.json"
        error_path = self.paths.state / f"errorlist_round_{tag}.json"
        check_path.write_text(
            json.dumps([item.model_dump(mode="json") for item in checklist], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        error_path.write_text(
            json.dumps([item.model_dump(mode="json") for item in errorlist], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return check_path, error_path

    def save_run_record(self, record: RunRecord) -> Path:
        path = self.paths.meta / "run_record.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_timing(
        self,
        *,
        stage: str,
        step: int | str,
        elapsed_ms: int,
        details: dict[str, Any] | None = None,
    ) -> Path:
        path = self.paths.meta / "timings.jsonl"
        payload: dict[str, Any] = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "step": str(step),
            "elapsed_ms": max(0, int(elapsed_ms)),
        }
        if details:
            payload["details"] = details
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def save_final_result(
        self,
        result: ModeResult,
        document: DocumentText,
        json_name: str,
        md_name: str,
        html_name: str,
    ) -> tuple[Path, Path, Path]:
        prepared_result = prepare_mode_result(result)
        json_path = self.paths.final / json_name
        md_path = self.paths.final / md_name
        html_path = self.paths.final / html_name
        json_path.write_text(prepared_result.model_dump_json(indent=2), encoding="utf-8")
        md_path.write_text(render_markdown_summary(prepared_result), encoding="utf-8")
        html_path.write_text(render_html_report(prepared_result, document), encoding="utf-8")
        return json_path, md_path, html_path
