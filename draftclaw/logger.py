"""
Structured logging utilities for DraftClaw runs.
"""

import json
import logging
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import (
    LIVE_STREAM_MODE,
    LIVE_STREAM_PREVIEW_CHARS,
    LIVE_STREAM_STEP_DELAY_MS,
    LIVE_STREAM_SUMMARY,
    LOGS_DIR,
)


class AgentLogger:
    """Write per-step structured logs into a session directory."""

    def __init__(self, live_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        logs_dir = LOGS_DIR
        logs_dir.mkdir(parents=True, exist_ok=True)

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = logs_dir / f"session_{self.session_id}"
        self.session_dir.mkdir(exist_ok=True)

        self.subdirs = {
            "pdf_parser": self.session_dir / "01_pdf_parser",
            "chunker": self.session_dir / "02_chunker",
            "plan_agent": self.session_dir / "03_plan_agent",
            "explore_agent": self.session_dir / "04_explore_agent",
            "summary_agent": self.session_dir / "05_summary_agent",
            "main": self.session_dir / "06_main",
            "review_report": self.session_dir / "07_review_report",
            "chunks": self.session_dir / "08_chunks",
            "stream_progress": self.session_dir / "09_stream_progress",
            "language_switch": self.session_dir / "10_language_switch",
            "report_renderer": self.session_dir / "11_report_renderer",
            "bbox_debug": self.session_dir / "12_bbox_debug",
            "vision_agent": self.session_dir / "13_vision_agent",
            "search_agent": self.session_dir / "14_search_agent",
            "recheck_agent": self.session_dir / "15_recheck_agent",
        }
        for subdir in self.subdirs.values():
            subdir.mkdir(parents=True, exist_ok=True)
        # Create input/output subdirectories for agents that use them
        for agent_name in ["plan_agent", "explore_agent", "vision_agent", "summary_agent", "search_agent", "recheck_agent"]:
            agent_dir = self.subdirs[agent_name]
            (agent_dir / "input").mkdir(exist_ok=True)
            (agent_dir / "output").mkdir(exist_ok=True)
            # For explore_agent, also create stage-specific subdirectories
            if agent_name == "explore_agent":
                for stage in ["stage_local", "stage_global", "stage_final"]:
                    (agent_dir / stage / "input").mkdir(parents=True, exist_ok=True)
                    (agent_dir / stage / "output").mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger(f"draftclaw.{self.session_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
            self.logger.addHandler(handler)

        self.log_index: List[Dict[str, Any]] = []
        self.step_counter = 0
        self._lock = threading.RLock()
        self.live_callback = live_callback

    def _next_step(self) -> int:
        with self._lock:
            self.step_counter += 1
            return self.step_counter

    @staticmethod
    def extract_display_data(
        data: Optional[Dict[str, Any]] = None,
        input_data: Optional[Any] = None,
        output_data: Optional[Any] = None,
        message: str = "",
    ) -> Dict[str, Any]:
        extracted = dict(data or {})

        def set_summary(value: Any) -> None:
            text = str(value or "").strip()
            if text and not extracted.get("summary_text"):
                extracted["summary_text"] = text

        def set_queries(value: Any) -> None:
            queries = [str(item).strip() for item in (value or []) if str(item).strip()]
            if queries and not extracted.get("query_list"):
                extracted["query_list"] = queries

        if isinstance(output_data, dict):
            set_summary(output_data.get("summary"))
            set_summary(output_data.get("analysis"))
            set_summary(output_data.get("chunk_purpose"))
            set_summary(output_data.get("core_content"))
            set_queries(output_data.get("query_list"))

        if isinstance(input_data, dict):
            set_summary(input_data.get("summary"))
            set_summary(input_data.get("chunk_purpose"))
            set_summary(input_data.get("core_content"))
            set_queries(input_data.get("query_list"))

        set_summary(extracted.get("summary"))
        set_summary(message)
        return extracted

    def log(
        self,
        agent_name: str,
        stage: str,
        chunk_id: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
        input_data: Optional[Any] = None,
        output_data: Optional[Any] = None,
        message: str = "",
        console: Optional[bool] = None,
    ) -> None:
        live_entry: Optional[Dict[str, Any]] = None
        with self._lock:
            timestamp = datetime.now().isoformat()
            step = self._next_step()

            log_entry = {
                "step": step,
                "timestamp": timestamp,
                "agent": agent_name,
                "stage": stage,
                "chunk_id": chunk_id,
                "message": message,
                "data": data,
                "input": input_data,
                "output": output_data,
            }

            filename = self._get_filename(agent_name, stage, chunk_id, step)
            self.log_index.append(
                {
                    "step": step,
                    "timestamp": timestamp,
                    "agent": agent_name,
                    "stage": stage,
                    "chunk_id": chunk_id,
                    "message": message,
                    "filename": filename,
                }
            )

            filepath = self._get_filepath(agent_name, stage, chunk_id, step)
            with open(filepath, "w", encoding="utf-8") as file_handle:
                json.dump(log_entry, file_handle, ensure_ascii=False, indent=2)
            input_md_filename = ""
            output_md_filename = ""
            input_md_path: Optional[Path] = None
            output_md_path: Optional[Path] = None
            stage_lower = stage.lower()
            markdown_input_data = input_data
            if markdown_input_data is None and "input" in stage_lower and data is not None:
                markdown_input_data = data
            markdown_output_data = output_data
            if markdown_output_data is None and "output" in stage_lower and data is not None:
                markdown_output_data = data

            if self._should_write_input_markdown(stage, markdown_input_data):
                input_md_path = filepath.with_suffix(".input.md")
                with open(input_md_path, "w", encoding="utf-8") as file_handle:
                    file_handle.write(
                        self._format_input_markdown(
                            step=step,
                            timestamp=timestamp,
                            agent_name=agent_name,
                            stage=stage,
                            chunk_id=chunk_id,
                            message=message,
                            input_data=markdown_input_data,
                        )
                    )
                input_md_filename = str(input_md_path.relative_to(self.session_dir))
                self.log_index[-1]["input_md_filename"] = input_md_filename

            if self._should_write_output_markdown(stage, markdown_output_data):
                output_md_path = filepath.with_suffix(".output.md")
                with open(output_md_path, "w", encoding="utf-8") as file_handle:
                    file_handle.write(
                        self._format_output_markdown(
                            step=step,
                            timestamp=timestamp,
                            agent_name=agent_name,
                            stage=stage,
                            chunk_id=chunk_id,
                            message=message,
                            output_data=markdown_output_data,
                        )
                    )
                output_md_filename = str(output_md_path.relative_to(self.session_dir))
                self.log_index[-1]["output_md_filename"] = output_md_filename

            mirror_filenames = self._mirror_explore_io_files(
                agent_name=agent_name,
                stage=stage,
                filepath=filepath,
                input_md_path=input_md_path,
                output_md_path=output_md_path,
            )
            if mirror_filenames:
                self.log_index[-1]["mirror_filenames"] = mirror_filenames

            live_entry = self._build_live_entry(
                step=step,
                timestamp=timestamp,
                agent_name=agent_name,
                stage=stage,
                chunk_id=chunk_id,
                message=message,
                data=data,
                input_data=input_data,
                output_data=output_data,
                filename=filename,
            )
            if input_md_filename:
                live_entry["data"]["input_md_filename"] = input_md_filename
            if output_md_filename:
                live_entry["data"]["output_md_filename"] = output_md_filename
            if mirror_filenames:
                live_entry["data"]["mirror_filenames"] = mirror_filenames

            should_print = console if console is not None else self._should_print_log(stage)
            if should_print:
                self.logger.info(self._build_console_message(log_entry))

        self._emit_live_entry(live_entry)

    def progress(
        self,
        phase: str,
        *,
        chunk_id: Optional[int] = None,
        status: str = "start",
        summary: str = "",
        level: int = 0,
        agent_name: str = "Progress",
        data: Optional[Dict[str, Any]] = None,
        pause_ms: Optional[int] = None,
    ) -> None:
        live_entry: Optional[Dict[str, Any]] = None
        with self._lock:
            timestamp = datetime.now().isoformat()
            step = self._next_step()
            stage = f"progress_{self._slugify(phase)}_{status}"

            log_entry = {
                "step": step,
                "timestamp": timestamp,
                "agent": agent_name,
                "stage": stage,
                "chunk_id": chunk_id,
                "message": summary,
                "data": {
                    "phase": phase,
                    "status": status,
                    "level": level,
                    **(data or {}),
                },
                "input": None,
                "output": None,
            }

            filename = self._get_progress_filename(step, phase, status, chunk_id)
            self.log_index.append(
                {
                    "step": step,
                    "timestamp": timestamp,
                    "agent": agent_name,
                    "stage": stage,
                    "chunk_id": chunk_id,
                    "message": summary,
                    "filename": filename,
                }
            )

            filepath = self.subdirs["stream_progress"] / filename
            with open(filepath, "w", encoding="utf-8") as file_handle:
                json.dump(log_entry, file_handle, ensure_ascii=False, indent=2)

            live_entry = self._build_live_entry(
                step=step,
                timestamp=timestamp,
                agent_name=agent_name,
                stage=stage,
                chunk_id=chunk_id,
                message=summary,
                data=log_entry["data"],
                input_data=None,
                output_data=None,
                filename=filename,
            )

            if LIVE_STREAM_SUMMARY:
                self.logger.info(self._build_progress_message(log_entry))

        self._emit_live_entry(live_entry)

        effective_pause_ms = pause_ms
        if effective_pause_ms is None and LIVE_STREAM_MODE == "progress" and status == "done":
            effective_pause_ms = LIVE_STREAM_STEP_DELAY_MS
        if effective_pause_ms and effective_pause_ms > 0:
            time.sleep(effective_pause_ms / 1000.0)

    def _build_live_entry(
        self,
        *,
        step: int,
        timestamp: str,
        agent_name: str,
        stage: str,
        chunk_id: Optional[int],
        message: str,
        data: Optional[Dict[str, Any]],
        input_data: Optional[Any],
        output_data: Optional[Any],
        filename: str,
    ) -> Dict[str, Any]:
        payload_data = self.extract_display_data(
            data=data,
            input_data=input_data,
            output_data=output_data,
            message=message,
        )
        payload_data.setdefault("step", step)
        payload_data.setdefault("filename", filename)
        if chunk_id is not None:
            payload_data.setdefault("chunk_id", chunk_id)
        return {
            "client_id": f"{self.session_id}-{step:04d}",
            "ts": timestamp,
            "timestamp": timestamp,
            "agent": agent_name,
            "stage": stage,
            "message": message,
            "data": payload_data,
        }

    def _emit_live_entry(self, entry: Optional[Dict[str, Any]]) -> None:
        if not entry or not callable(self.live_callback):
            return
        try:
            self.live_callback(entry)
        except Exception:
            return

    def _get_filename(self, agent_name: str, stage: str, chunk_id: Optional[int], step: int) -> str:
        if chunk_id is not None:
            return f"step{step:04d}_{agent_name}_{stage}_chunk{chunk_id:04d}.json"
        return f"step{step:04d}_{agent_name}_{stage}.json"

    def _get_filepath(self, agent_name: str, stage: str, chunk_id: Optional[int], step: int) -> Path:
        agent_lower = agent_name.lower().replace(" ", "_")
        stage_lower = stage.lower()

        # Determine the base directory for this agent
        if "pdfparser" in agent_lower:
            base_dir = self.subdirs["pdf_parser"]
        elif "chunker" in agent_lower:
            base_dir = self.subdirs["chunker"]
        elif "planagent" in agent_lower:
            base_dir = self.subdirs["plan_agent"]
        elif "exploreagent" in agent_lower:
            base_dir = self.subdirs["explore_agent"]
        elif "summaryagent" in agent_lower:
            base_dir = self.subdirs["summary_agent"]
        elif "searchagent" in agent_lower:
            base_dir = self.subdirs["search_agent"]
        elif "recheckagent" in agent_lower:
            base_dir = self.subdirs["recheck_agent"]
        elif "visionagent" in agent_lower:
            base_dir = self.subdirs["vision_agent"]
        elif "bboxdebug" in agent_lower:
            base_dir = self.subdirs["bbox_debug"]
        elif "languageswitchagent" in agent_lower:
            base_dir = self.subdirs["language_switch"]
        elif "reportrenderer" in agent_lower:
            base_dir = self.subdirs["report_renderer"]
        elif "main" in agent_lower:
            base_dir = self.subdirs["main"]
        else:
            base_dir = self.session_dir

        # Only route to input/output subdirectory for agents that have them
        has_input_output = any(
            name in agent_lower
            for name in ["planagent", "exploreagent", "visionagent", "summaryagent", "searchagent", "recheckagent"]
        )

        subdir = base_dir
        if has_input_output:
            # Route to input/output subdirectory based on stage
            if "input" in stage_lower:
                subdir = base_dir / "input"
            elif "output" in stage_lower:
                subdir = base_dir / "output"

            # For explore_agent, also check for stage-specific subdirectories
            # e.g., stage_local_input -> explore_agent/stage_local/input
            if "exploreagent" in agent_lower:
                for stage_prefix in ["stage_local", "stage_global", "stage_final"]:
                    if stage_prefix in stage_lower:
                        subdir = base_dir / stage_prefix
                        if "input" in stage_lower:
                            subdir = subdir / "input"
                        elif "output" in stage_lower:
                            subdir = subdir / "output"
                        break

        return subdir / self._get_filename(agent_name, stage, chunk_id, step)

    def _mirror_explore_io_files(
        self,
        *,
        agent_name: str,
        stage: str,
        filepath: Path,
        input_md_path: Optional[Path],
        output_md_path: Optional[Path],
    ) -> List[str]:
        agent_lower = agent_name.lower().replace(" ", "_")
        if "exploreagent" not in agent_lower:
            return []

        stage_lower = stage.lower()
        target_dir: Optional[Path] = None
        if "output" in stage_lower:
            target_dir = self.subdirs["explore_agent"] / "output"
        elif "input" in stage_lower or "llm_request" in stage_lower:
            target_dir = self.subdirs["explore_agent"] / "input"
        if not target_dir:
            return []

        target_dir.mkdir(parents=True, exist_ok=True)
        mirrored: List[str] = []
        for source_path in (input_md_path, output_md_path):
            if not source_path or not source_path.exists():
                continue
            if source_path.parent == target_dir:
                continue
            target_path = target_dir / source_path.name
            shutil.copyfile(source_path, target_path)
            mirrored.append(str(target_path.relative_to(self.session_dir)))
        return mirrored

    @staticmethod
    def _should_write_input_markdown(stage: str, input_data: Any) -> bool:
        if input_data is None:
            return False
        if isinstance(input_data, dict) and "llm_messages" in input_data:
            return True
        return "llm" in stage.lower()

    @staticmethod
    def _should_write_output_markdown(stage: str, output_data: Any) -> bool:
        if output_data is None:
            return False
        if isinstance(output_data, dict) and "llm_output" in output_data:
            return True
        return "llm" in stage.lower()

    def get_session_dir(self) -> Path:
        return self.session_dir

    @staticmethod
    def _slugify(value: str) -> str:
        lowered = value.lower()
        lowered = re.sub(r"[^\w\u4e00-\u9fff]+", "_", lowered, flags=re.UNICODE)
        return lowered.strip("_") or "phase"

    @staticmethod
    def _get_progress_filename(step: int, phase: str, status: str, chunk_id: Optional[int]) -> str:
        phase_slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", phase, flags=re.UNICODE).strip("_") or "phase"
        if chunk_id is not None:
            return f"step{step:04d}_Progress_{phase_slug}_{status}_chunk{chunk_id:04d}.json"
        return f"step{step:04d}_Progress_{phase_slug}_{status}.json"

    @staticmethod
    def _should_print_log(stage: str) -> bool:
        if not LIVE_STREAM_SUMMARY:
            return True
        if LIVE_STREAM_MODE != "progress":
            return True
        stage_lower = stage.lower()
        return "error" in stage_lower

    def _format_input_markdown(
        self,
        *,
        step: int,
        timestamp: str,
        agent_name: str,
        stage: str,
        chunk_id: Optional[int],
        message: str,
        input_data: Any,
    ) -> str:
        return self._format_payload_markdown(
            kind="Input",
            step=step,
            timestamp=timestamp,
            agent_name=agent_name,
            stage=stage,
            chunk_id=chunk_id,
            message=message,
            payload=input_data,
        )

    def _format_output_markdown(
        self,
        *,
        step: int,
        timestamp: str,
        agent_name: str,
        stage: str,
        chunk_id: Optional[int],
        message: str,
        output_data: Any,
    ) -> str:
        return self._format_payload_markdown(
            kind="Output",
            step=step,
            timestamp=timestamp,
            agent_name=agent_name,
            stage=stage,
            chunk_id=chunk_id,
            message=message,
            payload=output_data,
        )

    def _format_payload_markdown(
        self,
        *,
        kind: str,
        step: int,
        timestamp: str,
        agent_name: str,
        stage: str,
        chunk_id: Optional[int],
        message: str,
        payload: Any,
    ) -> str:
        if isinstance(payload, dict) and "llm_messages" in payload:
            return self._format_llm_input_markdown(payload["llm_messages"])
        if isinstance(payload, dict) and "llm_output" in payload:
            return self._format_llm_output_markdown(payload["llm_output"])

        lines = [
            f"# {agent_name} {kind}",
            "",
        ]

        if isinstance(payload, dict):
            for key, value in payload.items():
                lines.extend(self._format_markdown_value(str(key), value))
        else:
            lines.extend(self._format_markdown_value(kind.lower(), payload))
        return "\n".join(lines).rstrip() + "\n"

    def _format_llm_input_markdown(self, messages: Any) -> str:
        lines = ["# Model Input", ""]
        message_list = messages if isinstance(messages, list) else []
        if not message_list:
            lines.extend(["(empty)", ""])
            return "\n".join(lines).rstrip() + "\n"

        for message in message_list:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "message") or "message").strip()
            lines.extend([f"## {role}", ""])
            lines.extend(self._format_llm_content(message.get("content", "")))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _format_llm_output_markdown(self, output: Any) -> str:
        text = str(output if output is not None else "")
        return f"# Model Output\n\n{text.strip() if text.strip() else '(empty)'}\n"

    def _format_llm_content(self, content: Any) -> List[str]:
        if isinstance(content, str):
            return [content]
        if not isinstance(content, list):
            return [str(content)]

        lines: List[str] = []
        image_index = 0
        for item in content:
            if not isinstance(item, dict):
                lines.append(str(item))
                continue
            item_type = str(item.get("type", "") or "").strip()
            if item_type == "text":
                text = str(item.get("text", "") or "")
                if text:
                    lines.append(text)
                continue
            if item_type == "image_url":
                image_url = item.get("image_url", {})
                url = ""
                if isinstance(image_url, dict):
                    url = str(image_url.get("url", "") or "")
                else:
                    url = str(image_url or "")
                image_index += 1
                lines.append(f"![LLM image {image_index}]({url})")
                continue
            lines.append(json.dumps(item, ensure_ascii=False))
        return lines

    def _format_markdown_value(self, title: str, value: Any) -> List[str]:
        key = title.lower()
        if key in {"image_inputs", "images", "screenshots"}:
            return self._format_image_inputs_markdown(title, value)
        if key in {"plan_output", "plan"} and isinstance(value, dict):
            return self._format_plan_markdown(title, value)
        if key == "explore_output" and isinstance(value, dict):
            return self._format_explore_output_markdown(title, value)
        if key in {
            "local_error_list",
            "global_error_list",
            "final_error_list",
            "error_list",
            "candidate_issues",
            "issues",
            "vision_rejected_issues",
        }:
            return self._format_issue_list_markdown(title, value)
        if key == "search_requests":
            return self._format_search_requests_markdown(title, value)
        if key == "search_results":
            return self._format_search_results_markdown(title, value)
        if "metrics" in key or key.startswith("_"):
            return self._format_metrics_markdown(title, value)

        lines = [f"## {title}", ""]
        if isinstance(value, str):
            parsed = self._parse_json_string(value)
            if parsed is not None:
                lines.extend(self._format_markdown_value(title, parsed)[2:])
                return lines
            lines.extend([value if value.strip() else "(empty)", ""])
            return lines
        if isinstance(value, dict):
            lines.extend(self._format_generic_dict_markdown(value))
            return lines
        if isinstance(value, list):
            if self._looks_like_issue_list(value):
                return self._format_issue_list_markdown(title, value)
            lines.extend(self._format_generic_list_markdown(value))
            return lines
        lines.extend(["```text", str(value), "```", ""])
        return lines

    def _format_plan_markdown(self, title: str, value: Dict[str, Any]) -> List[str]:
        lines = [f"## {title}", ""]
        for field in ("section_role", "chunk_purpose", "core_content", "visual_element_role"):
            text = str(value.get(field, "") or "").strip()
            if text:
                lines.append(f"- {field}: {text}")

        queries = value.get("query_list", [])
        if isinstance(queries, str):
            queries = [queries]
        queries = [str(item).strip() for item in queries if str(item).strip()] if isinstance(queries, list) else []
        if queries:
            lines.extend(["", "### query_list", ""])
            lines.extend(f"- {item}" for item in queries)

        if any(str(key).startswith("_") or "metrics" in str(key).lower() for key in value):
            lines.extend(["", "_Technical metrics omitted from Markdown view; see the JSON log for raw metadata._"])
        lines.append("")
        return lines

    def _format_explore_output_markdown(self, title: str, value: Dict[str, Any]) -> List[str]:
        lines = [f"## {title}", ""]
        for list_key in ("local_error_list", "global_error_list", "final_error_list", "error_list"):
            items = value.get(list_key)
            if items is not None:
                lines.extend(self._format_issue_list_markdown(list_key, items))
        for list_key in ("local_search_requests", "global_search_requests", "search_requests"):
            items = value.get(list_key)
            if items is not None:
                lines.extend(self._format_search_requests_markdown(list_key, items))
        for list_key in ("local_search_results", "global_search_results", "search_results"):
            items = value.get(list_key)
            if items is not None:
                lines.extend(self._format_search_results_markdown(list_key, items))
        if any(str(key).startswith("_") or "metrics" in str(key).lower() for key in value):
            lines.extend(["_Technical metrics omitted from Markdown view; see the JSON log for raw metadata._", ""])
        return lines

    def _format_issue_list_markdown(self, title: str, value: Any) -> List[str]:
        lines = [f"## {title}", ""]
        issues = value if isinstance(value, list) else []
        if not issues:
            lines.extend(["(empty)", ""])
            return lines

        for index, issue in enumerate(issues, start=1):
            if not isinstance(issue, dict):
                lines.extend([f"### Issue {index}", "", str(issue), ""])
                continue
            issue_type = str(issue.get("type", "unknown") or "unknown").strip()
            severity = str(issue.get("severity", "unknown") or "unknown").strip()
            lines.extend([f"### Issue {index}: {issue_type} / {severity}", ""])
            for field in ("location", "evidence", "source_stage"):
                if field not in issue:
                    continue
                rendered = self._format_inline_value(issue.get(field))
                lines.append(f"- {field}: {rendered}")

            description = str(issue.get("description", "") or "").strip()
            reasoning = str(issue.get("reasoning", "") or "").strip()
            if description:
                lines.extend(["", "#### description", "", description])
            if reasoning:
                lines.extend(["", "#### reasoning", "", reasoning])
            if issue.get("search_result"):
                lines.extend(["", "#### search_result", ""])
                lines.extend(self._format_generic_dict_markdown(issue.get("search_result", {})))
            if issue.get("vision_validation"):
                lines.extend(["", "#### vision_validation", ""])
                lines.extend(self._format_generic_dict_markdown(issue.get("vision_validation", {})))
            lines.append("")
        return lines

    def _format_image_inputs_markdown(self, title: str, value: Any) -> List[str]:
        lines = [f"## {title}", ""]
        images = value if isinstance(value, list) else []
        if not images:
            lines.extend(["(empty)", ""])
            return lines

        lines.extend(
            [
                f"{len(images)} image(s). When a `local_path` is present, the LLM payload is generated from that file as a base64 data URL; the path below is only for log preview.",
                "",
            ]
        )
        for index, image in enumerate(images, start=1):
            if not isinstance(image, dict):
                lines.extend([f"### Image {index}", "", str(image), ""])
                continue
            local_path = str(image.get("local_path", "") or "").strip()
            caption = str(image.get("caption", "") or "").strip()
            if not caption:
                caption = " ".join(
                    str(item).strip()
                    for item in image.get("image_caption", [])
                    if str(item).strip()
                )
            lines.extend([f"### Image {index}", ""])
            lines.append(f"- page_idx: {image.get('page_idx', 'N/A')}")
            lines.append(f"- sent_to_model: {'yes, as image data' if local_path else 'no local image file'}")
            if image.get("merged_image_count"):
                lines.append(f"- merged_image_count: {image.get('merged_image_count')}")
            if image.get("img_path"):
                lines.append(f"- markdown_ref: {image.get('img_path')}")
            source_paths = image.get("source_image_paths", [])
            if source_paths:
                lines.append(f"- source_image_paths: {self._format_inline_value(source_paths)}")
            if caption:
                lines.append(f"- caption: {caption}")
            if local_path:
                preview_target = self._markdown_image_target(local_path)
                lines.extend(["", f"![Image {index}]({preview_target})"])
            lines.append("")
        return lines

    def _format_search_requests_markdown(self, title: str, value: Any) -> List[str]:
        lines = [f"## {title}", ""]
        requests = value if isinstance(value, list) else []
        if not requests:
            lines.extend(["(empty)", ""])
            return lines
        for index, item in enumerate(requests, start=1):
            if not isinstance(item, dict):
                lines.append(f"{index}. {item}")
                continue
            request_id = str(item.get("request_id", f"request-{index}") or f"request-{index}").strip()
            lines.append(f"{index}. `{request_id}`")
            if item.get("goal"):
                lines.append(f"   goal: {item.get('goal')}")
            if item.get("query"):
                lines.append(f"   query: `{item.get('query')}`")
        lines.append("")
        return lines

    def _format_search_results_markdown(self, title: str, value: Any) -> List[str]:
        lines = [f"## {title}", ""]
        results = value if isinstance(value, list) else []
        if not results:
            lines.extend(["(empty)", ""])
            return lines
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                lines.extend([f"### Result {index}", "", str(item), ""])
                continue
            lines.extend([f"### Result {index}", ""])
            for field in ("request_id", "query", "summary", "error"):
                if item.get(field):
                    lines.append(f"- {field}: {item.get(field)}")
            sources = item.get("sources", [])
            if isinstance(sources, list) and sources:
                lines.extend(["", "#### sources"])
                for source_index, source in enumerate(sources[:5], start=1):
                    if isinstance(source, dict):
                        title_text = str(source.get("title", "") or source.get("url", "") or f"source {source_index}").strip()
                        url_text = str(source.get("url", "") or "").strip()
                        snippet = str(source.get("snippet", "") or "").strip()
                        line = f"- {title_text}"
                        if url_text:
                            line += f" - {url_text}"
                        lines.append(line)
                        if snippet:
                            lines.append(f"  snippet: {snippet}")
                    else:
                        lines.append(f"- {source}")
            lines.append("")
        return lines

    def _format_metrics_markdown(self, title: str, value: Any) -> List[str]:
        lines = [f"## {title}", ""]
        if isinstance(value, dict):
            parts = []
            for field in ("model", "elapsed_seconds", "prompt_tokens", "completion_tokens", "total_tokens"):
                if value.get(field) is not None:
                    parts.append(f"{field}={value.get(field)}")
            lines.append(" | ".join(parts) if parts else "_Technical metadata omitted from Markdown view._")
        else:
            lines.append("_Technical metadata omitted from Markdown view._")
        lines.append("")
        return lines

    def _format_generic_dict_markdown(self, value: Dict[str, Any]) -> List[str]:
        lines: List[str] = []
        nested_items: List[tuple[str, Any]] = []
        omitted_metadata = False

        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_text.startswith("_") or "metrics" in key_lower or key_lower == "raw_usage":
                omitted_metadata = True
                continue
            if self._is_simple_markdown_value(item):
                lines.append(f"- {key_text}: {self._format_inline_value(item)}")
            else:
                nested_items.append((key_text, item))

        if not lines and not nested_items and not omitted_metadata:
            lines.append("(empty)")
        if lines:
            lines.append("")
        for nested_key, nested_value in nested_items:
            lines.extend(self._format_markdown_value(nested_key, nested_value))
        if omitted_metadata:
            lines.extend(["_Technical metrics omitted from Markdown view; see the JSON log for raw metadata._", ""])
        return lines

    def _format_generic_list_markdown(self, value: List[Any]) -> List[str]:
        lines: List[str] = []
        if not value:
            return ["(empty)", ""]
        if all(self._is_simple_markdown_value(item) for item in value):
            lines.extend(f"- {self._format_inline_value(item)}" for item in value)
            lines.append("")
            return lines
        for index, item in enumerate(value, start=1):
            lines.extend([f"### Item {index}", ""])
            if isinstance(item, dict):
                lines.extend(self._format_generic_dict_markdown(item))
            else:
                lines.extend(self._format_markdown_value("value", item)[2:])
        return lines

    @staticmethod
    def _is_simple_markdown_value(value: Any) -> bool:
        return value is None or isinstance(value, (bool, int, float)) or (
            isinstance(value, str) and len(value) <= 500
        )

    @staticmethod
    def _looks_like_issue_list(value: Any) -> bool:
        return isinstance(value, list) and any(
            isinstance(item, dict)
            and {"type", "description"}.issubset(set(item.keys()))
            for item in value
        )

    @staticmethod
    def _format_inline_value(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(f"`{str(item).strip()}`" for item in value if str(item).strip()) or "(empty)"
        if isinstance(value, dict):
            compact = {
                str(key): item
                for key, item in value.items()
                if item is not None and not str(key).startswith("_")
            }
            return json.dumps(compact, ensure_ascii=False)
        text = str(value if value is not None else "").strip()
        return f"`{text}`" if text else "(empty)"

    @staticmethod
    def _markdown_image_target(local_path: str) -> str:
        normalized = str(local_path).replace("\\", "/")
        return normalized.replace(" ", "%20")

    @staticmethod
    def _parse_json_string(value: str) -> Any:
        if not AgentLogger._looks_like_json(value):
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _looks_like_json(value: str) -> bool:
        text = value.strip()
        return (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))

    def _build_console_message(self, log_entry: Dict[str, Any]) -> str:
        if not LIVE_STREAM_SUMMARY:
            return (
                f"[Step {log_entry['step']}] [{log_entry['agent']}] {log_entry['stage']} "
                f"| Chunk: {log_entry['chunk_id']} | {log_entry['message']}"
            )

        agent_name = log_entry["agent"]
        stage = log_entry["stage"]
        chunk_id = log_entry["chunk_id"]
        data = log_entry.get("data") or {}
        input_data = log_entry.get("input") or {}
        output_data = log_entry.get("output") or {}

        prefix = f"[live][{agent_name}]"
        if chunk_id is not None:
            prefix += f"[chunk {chunk_id:04d}]"

        details: List[str] = []

        llm_metrics = data.get("llm_metrics") if isinstance(data, dict) else None
        if not llm_metrics and isinstance(output_data, dict):
            llm_metrics = output_data.get("llm_metrics")

        if agent_name == "Main" and stage == "document_assets":
            if data.get("parser_backend"):
                details.append(f"parser={data.get('parser_backend')}")
            details.append(f"images={data.get('parser_image_count', data.get('mineru_image_count', 0))}")
            details.append(f"local_images={data.get('available_local_image_count', 0)}")
            details.append(f"markdown_image_refs={data.get('markdown_image_markdown_count', 0)}")
            details.append(f"llm_mode={data.get('llm_input_mode', 'text-only')}")
            details.append(f"bbox={'yes' if data.get('has_bbox_json') else 'no'}")
        elif agent_name == "Main" and stage == "chunk_review_audit":
            details.append(f"excerpt={data.get('excerpt_char_count', 0)} chars")
            details.append(f"images={data.get('chunk_image_input_count', 0)}")
            details.append(f"removed_image_refs={data.get('removed_image_markdown_lines', 0)}")
            details.append(f"captions={data.get('retained_caption_count', 0)}")
            details.append(f"tables={data.get('retained_table_count', 0)}")
        elif agent_name == "Main" and stage == "chunk_complete":
            if isinstance(output_data, dict) and output_data:
                details.append(f"issues={output_data.get('issues_found', 0)}")
                if isinstance(output_data.get("metrics"), dict):
                    details.append(self._format_llm_metrics(output_data["metrics"]))
            else:
                details.append(f"chunks={data.get('chunk_count', 0)}")
                if "elapsed_seconds" in data:
                    details.append(f"{float(data['elapsed_seconds']):.2f}s")
        elif agent_name == "Main" and stage == "bbox_enriched":
            best_match = output_data.get("best_bbox_match") if isinstance(output_data, dict) else None
            if best_match:
                details.append(f"page={best_match.get('page')}")
                details.append(f"source={best_match.get('source')}")
                details.append(f"score={best_match.get('score')}")
            else:
                details.append("no_match")
        elif agent_name == "Main" and stage == "metrics":
            details.append(self._format_llm_metrics(data))
            details.append(f"wall={data.get('wall_seconds', 0):.2f}s")
        elif agent_name == "PlanAgent" and stage == "input":
            details.append(f"excerpt={len(str(input_data.get('chunk_content', '')))} chars")
        elif agent_name == "PlanAgent" and stage == "llm_request":
            details.append(f"model={data.get('model', 'unknown')}")
            details.append(f"prompt~{data.get('prompt_tokens', 0)} tok")
            details.append(f"images={data.get('image_count', 0)}")
        elif agent_name == "PlanAgent" and stage == "output":
            details.append(f"queries={len(output_data.get('query_list', []))}")
            details.append(f"images={data.get('image_count', 0)}")
            details.append(self._format_llm_metrics(data.get("llm_metrics", {})))
            details.append(self._preview_text(output_data.get("summary", "")))
        elif agent_name == "ExploreAgent" and stage == "stage1_input":
            details.append(f"queries={len(input_data.get('query_list', []))}")
            details.append(f"overview={len(str(input_data.get('document_overview', '')))} chars")
            details.append(f"images={len(input_data.get('image_inputs', []))}")
        elif agent_name == "ExploreAgent" and stage == "llm_request":
            details.append(f"model={data.get('model', 'unknown')}")
            details.append(f"prompt~{data.get('prompt_tokens', 0)} tok")
            details.append(f"images={data.get('image_count', 0)}")
        elif agent_name == "ExploreAgent" and stage == "stage3_output":
            issues = output_data.get("issues", [])
            issue_labels = ", ".join(
                f"{item.get('type', '?')}/{item.get('severity', '?')}" for item in issues[:3]
            )
            details.append(f"issues={len(issues)}")
            details.append(f"images={data.get('image_count', 0)}")
            if issue_labels:
                details.append(issue_labels)
            details.append(self._format_llm_metrics(data.get("llm_metrics", {})))
        elif agent_name == "VisionAgent" and stage == "input":
            details.append(f"screens={len(input_data.get('screenshots', []))}")
        elif agent_name == "VisionAgent" and stage == "llm_request":
            details.append(f"model={data.get('model', 'unknown')}")
            details.append(f"prompt~{data.get('prompt_tokens', 0)} tok")
            details.append(f"images={data.get('image_count', 0)}")
        elif agent_name == "VisionAgent" and stage == "output":
            details.append(f"decision={output_data.get('decision', 'unknown')}")
            details.append(f"confidence={output_data.get('confidence', 'unknown')}")
            details.append(f"images={data.get('image_count', 0)}")
            details.append(self._format_llm_metrics(data.get("llm_metrics", {})))
        elif agent_name == "LanguageSwitchAgent" and stage == "detect":
            details.append(f"source={data.get('detected_language', 'unknown')}")
            details.append(f"target={data.get('target_language', 'unknown')}")
            details.append(f"switch={data.get('switch_needed', False)}")
        elif agent_name == "LanguageSwitchAgent" and stage == "llm_request":
            details.append(f"model={data.get('model', 'unknown')}")
            details.append(f"batch={data.get('batch_index', 0)}")
            details.append(f"issues={data.get('issue_count', 0)}")
        elif agent_name == "LanguageSwitchAgent" and stage == "output":
            details.append(f"batch={data.get('batch_index', 0)}")
            details.append(f"translated={data.get('translated_issue_count', 0)}")
            details.append(self._format_llm_metrics(data.get("llm_metrics", {})))
        elif agent_name == "ReportRenderer" and stage == "output":
            details.append(f"issues={data.get('issue_count', 0)}")
            details.append(f"path={data.get('html_path', '')}")

        if not details and llm_metrics:
            details.append(self._format_llm_metrics(llm_metrics))

        suffix = log_entry["message"]
        if details:
            suffix = f"{suffix} | {' | '.join(detail for detail in details if detail)}"
        return f"{prefix} {suffix}".strip()

    def _build_progress_message(self, log_entry: Dict[str, Any]) -> str:
        data = log_entry.get("data") or {}
        phase = str(data.get("phase", "") or "Progress")
        status = str(data.get("status", "info") or "info")
        level = int(data.get("level", 0) or 0)
        summary = str(log_entry.get("message", "") or "").strip()
        chunk_id = log_entry.get("chunk_id")

        indent = "  " * max(level, 0)
        chunk_prefix = f"[Chunk {chunk_id:04d}] " if chunk_id is not None else ""

        if status == "heading":
            body = f"{chunk_prefix}{phase}"
        elif status == "start":
            body = f"{chunk_prefix}{indent}{phase}中..."
        elif status == "done":
            body = f"{chunk_prefix}{indent}{phase}完毕 [OK]"
        else:
            body = f"{chunk_prefix}{indent}{phase}"

        if summary:
            body = f"{body} | {summary}"

        return body

    @staticmethod
    def _preview_text(value: Any) -> str:
        text = str(value or "").strip().replace("\n", " ")
        if not text:
            return ""
        if len(text) <= LIVE_STREAM_PREVIEW_CHARS:
            return text
        return text[: LIVE_STREAM_PREVIEW_CHARS - 3] + "..."

    @staticmethod
    def _format_llm_metrics(metrics: Dict[str, Any]) -> str:
        if not isinstance(metrics, dict) or not metrics:
            return ""
        elapsed = float(metrics.get("elapsed_seconds", metrics.get("llm_elapsed_seconds", 0.0)) or 0.0)
        total_tokens = int(metrics.get("total_tokens", 0) or 0)
        usage_source = str(metrics.get("usage_source", metrics.get("usage_sources", "")) or "")
        if usage_source:
            return f"{elapsed:.2f}s | tok={total_tokens} ({usage_source})"
        return f"{elapsed:.2f}s | tok={total_tokens}"

    def save_review_report(self, report_data: Dict[str, Any], filename: str = "review_report.json") -> Path:
        filepath = self.subdirs["review_report"] / filename
        with open(filepath, "w", encoding="utf-8") as file_handle:
            json.dump(report_data, file_handle, ensure_ascii=False, indent=2)
        return filepath

    def save_review_html(self, html_content: str, filename: str = "review_report.html") -> Path:
        filepath = self.subdirs["review_report"] / filename
        with open(filepath, "w", encoding="utf-8") as file_handle:
            file_handle.write(html_content)
        return filepath

    def save_chunks(self, chunks: List[Any]) -> None:
        chunks_data = []
        for chunk in chunks:
            chunks_data.append(
                {
                    "id": chunk.id,
                    "char_count": chunk.char_count,
                    "start_pos": chunk.start_pos,
                    "end_pos": chunk.end_pos,
                    "content_preview": chunk.content[:500] + "..." if len(chunk.content) > 500 else chunk.content,
                }
            )

        filepath = self.subdirs["chunks"] / "chunks_info.json"
        with open(filepath, "w", encoding="utf-8") as file_handle:
            json.dump(chunks_data, file_handle, ensure_ascii=False, indent=2)

        for chunk in chunks:
            chunk_file = self.subdirs["chunks"] / f"chunk{chunk.id:04d}_content.txt"
            with open(chunk_file, "w", encoding="utf-8") as file_handle:
                file_handle.write(chunk.content)

    def save_index(self) -> None:
        filepath = self.session_dir / "log_index.json"
        with open(filepath, "w", encoding="utf-8") as file_handle:
            json.dump(
                {
                    "session_id": self.session_id,
                    "total_steps": self.step_counter,
                    "total_logs": len(self.log_index),
                    "logs": self.log_index,
                },
                file_handle,
                ensure_ascii=False,
                indent=2,
            )
