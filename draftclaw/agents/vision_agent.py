"""
Vision validation agent for bbox-grounded issue verification.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.llm_utils import (
    ChatCompletionClient,
    LLMCallResult,
    build_multimodal_user_content,
    estimate_message_tokens,
    estimate_text_tokens,
    extract_json_payload,
    is_multimodal_model,
)
import config
from logger import AgentLogger
from prompt_loader import load_prompt_section_text, render_prompt_section_template


DEFAULT_VISION_SYSTEM_PROMPT = """You are a rigorous multimodal verifier for academic-paper review issues.

Your task is to verify whether a candidate issue from a review pipeline is actually supported by the provided PDF screenshots.
Use screenshot pixels plus OCR text extracted from the same crops as auxiliary evidence.
Return JSON only."""

DEFAULT_VISION_USER_PROMPT = """Validate this candidate issue against the provided PDF screenshots.

Candidate issue:
{{issue_json}}

BBox screenshot metadata:
{{screenshot_json}}"""

MOCK_MODE = False


class VisionValidationAgent:
    """Validate bbox-grounded issues against rendered PDF screenshots."""

    def __init__(self, logger: Optional[AgentLogger] = None):
        self.logger = logger
        self.system_prompt = load_prompt_section_text(
            "vision_prompt.md",
            "system",
            fallback=DEFAULT_VISION_SYSTEM_PROMPT,
        )
        self.model_name = config.RECHECK_VLM_MODEL
        self.client = ChatCompletionClient(
            api_url=config.RECHECK_VLM_API_URL,
            api_key=config.RECHECK_VLM_API_KEY,
            model=self.model_name,
            default_timeout=120,
            max_retries=3,
        )

    @property
    def enabled(self) -> bool:
        return is_multimodal_model(self.model_name)

    def validate_issue(
        self,
        *,
        issue: Dict[str, Any],
        issue_index: int,
        chunk_id: Optional[int],
        screenshots: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        screenshot_inputs = [item for item in screenshots if item.get("local_path")]
        screenshot_summary = []
        original_evidence = issue.get("evidence_original", issue.get("evidence"))
        original_location = issue.get("location_original", issue.get("location"))
        for item in screenshot_inputs:
            matched = item.get("matched_text", "")
            ocr_text = item.get("ocr_text", "")
            # Include both original evidence/location and matched text for transparency
            item_summary = {
                "kind": item.get("kind"),
                "page": item.get("page"),
                "bbox": item.get("bbox"),
                "local_path": item.get("local_path"),
            }
            # If this is an evidence screenshot, include original evidence for comparison
            if item.get("kind") == "evidence" and original_evidence:
                item_summary["original_evidence"] = original_evidence
            # If this is a location screenshot, include original location for comparison
            if item.get("kind") == "location" and original_location:
                item_summary["original_location"] = original_location
            # Always include matched text found by bbox lookup
            item_summary["matched_text"] = matched
            if ocr_text:
                item_summary["ocr_text"] = ocr_text
                item_summary["ocr_source"] = item.get("ocr_source", "")
            screenshot_summary.append(item_summary)
        issue_payload = {
            "type": issue.get("type"),
            "severity": issue.get("severity"),
            "description": issue.get("description"),
            "evidence": issue.get("evidence"),
            "location": issue.get("location"),
            "reasoning": issue.get("reasoning"),
            "chunk_id": issue.get("chunk_id"),
            "evidence_display": issue.get("evidence_display"),
            "location_display": issue.get("location_display"),
            "evidence_anchor_ids": issue.get("evidence_anchor_ids"),
            "location_anchor_ids": issue.get("location_anchor_ids"),
            # Preserve original evidence and location for transparency
            "original_evidence": original_evidence,
            "original_location": original_location,
        }
        artifact_bundle = self._prepare_validation_artifacts(
            chunk_id=chunk_id,
            issue_index=issue_index,
            issue_payload=issue_payload,
            screenshot_summary=screenshot_summary,
            screenshot_inputs=screenshot_inputs,
        )

        if self.logger:
            self.logger.log(
                "VisionAgent",
                "input",
                chunk_id=chunk_id,
                input_data={
                    "issue_index": issue_index,
                    "issue": issue_payload,
                    "screenshots": screenshot_summary,
                    "artifact_dir": artifact_bundle.get("relative_dir", ""),
                },
                message="Starting vision validation",
            )

        if not screenshot_inputs:
            result = {
                "validated": False,
                "decision": "skip",
                "confidence": "low",
                "reason": "No bbox screenshots were available for this issue.",
                "model": self.model_name,
                "screenshot_count": 0,
            }
            self._write_validation_output_artifacts(
                artifact_bundle=artifact_bundle,
                llm_output="",
                parsed_result=result,
            )
            if self.logger:
                self.logger.log(
                    "VisionAgent",
                    "output",
                    chunk_id=chunk_id,
                    data={"image_count": 0, "llm_metrics": {}},
                    output_data=result,
                    message="Skipped vision validation",
                )
            return result

        if not self.enabled:
            result = {
                "validated": False,
                "decision": "skip",
                "confidence": "low",
                "reason": f"Model `{self.model_name}` is not multimodal.",
                "model": self.model_name,
                "screenshot_count": len(screenshot_inputs),
            }
            self._write_validation_output_artifacts(
                artifact_bundle=artifact_bundle,
                llm_output="",
                parsed_result=result,
            )
            if self.logger:
                self.logger.log(
                    "VisionAgent",
                    "output",
                    chunk_id=chunk_id,
                    data={"image_count": len(screenshot_inputs), "llm_metrics": {}},
                    output_data=result,
                    message="Vision model unavailable",
                )
            return result

        user_prompt = render_prompt_section_template(
            "vision_prompt.md",
            "user",
            fallback=DEFAULT_VISION_USER_PROMPT,
            issue_json=json.dumps(issue_payload, ensure_ascii=False, indent=2),
            screenshot_json=json.dumps(screenshot_summary, ensure_ascii=False, indent=2),
        )
        self._write_validation_request_artifacts(
            artifact_bundle=artifact_bundle,
            issue_payload=issue_payload,
            screenshot_summary=screenshot_summary,
            user_prompt=user_prompt,
        )
        user_content = build_multimodal_user_content(
            user_prompt,
            screenshot_inputs,
            min_pixels=config.LLM_IMAGE_MIN_PIXELS,
            max_pixels=config.LLM_IMAGE_MAX_PIXELS,
        )
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        if self.logger:
            self.logger.log(
                "VisionAgent",
                "llm_input",
                chunk_id=chunk_id,
                data={
                    "model": self.model_name,
                    "prompt_tokens": estimate_message_tokens(messages),
                    "image_count": len(screenshot_inputs),
                    "artifact_dir": artifact_bundle.get("relative_dir", ""),
                },
                input_data={"llm_messages": messages},
                message="Calling vision model",
            )

        llm_result = self._call_llm(user_content)
        if self.logger:
            self.logger.log(
                "VisionAgent",
                "llm_output",
                chunk_id=chunk_id,
                data={"llm_metrics": llm_result.to_dict()},
                output_data={"llm_output": llm_result.content},
                message="Vision model raw output",
            )
        parsed = self._normalize_result(extract_json_payload(llm_result.content))
        parsed.update(
            {
                "validated": parsed["decision"] != "skip",
                "model": self.model_name,
                "screenshot_count": len(screenshot_inputs),
            }
        )
        self._write_validation_output_artifacts(
            artifact_bundle=artifact_bundle,
            llm_output=llm_result.content,
            parsed_result=parsed,
        )

        if self.logger:
            self.logger.log(
                "VisionAgent",
                "output",
                chunk_id=chunk_id,
                data={"image_count": len(screenshot_inputs), "llm_metrics": llm_result.to_dict()},
                output_data=parsed,
                message=f"Vision validation decided {parsed['decision']}",
            )

        parsed["_llm_metrics"] = llm_result.to_dict()
        return parsed

    def _prepare_validation_artifacts(
        self,
        *,
        chunk_id: Optional[int],
        issue_index: int,
        issue_payload: Dict[str, Any],
        screenshot_summary: List[Dict[str, Any]],
        screenshot_inputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        bundle = self._validation_artifact_dirs(chunk_id=chunk_id, issue_index=issue_index)
        if not bundle:
            return {}

        copied_screenshots = self._copy_screenshot_artifacts(
            screenshot_inputs=screenshot_inputs,
            images_dir=bundle["images_dir"],
            case_dir=bundle["case_dir"],
        )
        bundle["copied_screenshots"] = copied_screenshots

        self._write_json_file(
            bundle["input_dir"] / "issue.json",
            {"issue_index": issue_index, "chunk_id": chunk_id, "issue": issue_payload},
        )
        self._write_json_file(
            bundle["input_dir"] / "screenshots.json",
            {
                "screenshot_count": len(screenshot_summary),
                "screenshots": copied_screenshots or screenshot_summary,
            },
        )
        self._write_markdown_file(
            bundle["input_dir"] / "issue.md",
            self._render_validation_issue_markdown(
                issue_payload=issue_payload,
                screenshot_summary=copied_screenshots or screenshot_summary,
            ),
        )
        return bundle

    def _write_validation_request_artifacts(
        self,
        *,
        artifact_bundle: Dict[str, Any],
        issue_payload: Dict[str, Any],
        screenshot_summary: List[Dict[str, Any]],
        user_prompt: str,
    ) -> None:
        if not artifact_bundle:
            return

        request_payload = {
            "model": self.model_name,
            "system_prompt": self.system_prompt,
            "user_prompt": user_prompt,
            "issue": issue_payload,
            "screenshots": artifact_bundle.get("copied_screenshots") or screenshot_summary,
        }
        self._write_json_file(artifact_bundle["input_dir"] / "model_request.json", request_payload)
        self._write_markdown_file(
            artifact_bundle["input_dir"] / "model_request.md",
            self._render_validation_request_markdown(
                issue_payload=issue_payload,
                screenshot_summary=artifact_bundle.get("copied_screenshots") or screenshot_summary,
                user_prompt=user_prompt,
            ),
        )

    def _write_validation_output_artifacts(
        self,
        *,
        artifact_bundle: Dict[str, Any],
        llm_output: str,
        parsed_result: Dict[str, Any],
    ) -> None:
        if not artifact_bundle:
            return

        self._write_text_file(artifact_bundle["output_dir"] / "model_output.txt", str(llm_output or "").strip())
        self._write_markdown_file(
            artifact_bundle["output_dir"] / "model_output.md",
            "# Vision Model Output\n\n" + (str(llm_output or "").strip() or "(empty)") + "\n",
        )
        self._write_json_file(artifact_bundle["output_dir"] / "parsed_result.json", parsed_result)
        self._write_markdown_file(
            artifact_bundle["output_dir"] / "parsed_result.md",
            "# Vision Parsed Result\n\n```json\n"
            + json.dumps(parsed_result, ensure_ascii=False, indent=2)
            + "\n```\n",
        )

    def _validation_artifact_dirs(
        self,
        *,
        chunk_id: Optional[int],
        issue_index: int,
    ) -> Dict[str, Any]:
        if not self.logger or not hasattr(self.logger, "subdirs"):
            return {}
        vision_dir = self.logger.subdirs.get("vision_agent")
        if not vision_dir:
            return {}

        chunk_label = (
            f"chunk{int(chunk_id):04d}"
            if isinstance(chunk_id, int) and chunk_id >= 0
            else "chunk_na"
        )
        case_dir = vision_dir / "validations" / f"{chunk_label}_issue{int(issue_index):04d}"
        input_dir = case_dir / "input"
        output_dir = case_dir / "output"
        images_dir = case_dir / "images"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
        relative_dir = ""
        session_dir = getattr(self.logger, "session_dir", None)
        if session_dir:
            relative_dir = case_dir.relative_to(session_dir).as_posix()
        return {
            "case_dir": case_dir,
            "input_dir": input_dir,
            "output_dir": output_dir,
            "images_dir": images_dir,
            "relative_dir": relative_dir,
        }

    def _copy_screenshot_artifacts(
        self,
        *,
        screenshot_inputs: List[Dict[str, Any]],
        images_dir: Path,
        case_dir: Path,
    ) -> List[Dict[str, Any]]:
        copied: List[Dict[str, Any]] = []
        for index, item in enumerate(screenshot_inputs, start=1):
            local_path = str(item.get("local_path", "") or "").strip()
            if not local_path:
                continue
            source_path = Path(local_path)
            if not source_path.exists():
                continue

            kind = str(item.get("kind", "image") or "image").strip().lower() or "image"
            page = int(item.get("page", 0) or 0)
            suffix = source_path.suffix or ".png"
            target_name = f"{index:02d}_{kind}_page{page:03d}{suffix}"
            target_path = images_dir / target_name
            if source_path.resolve() != target_path.resolve():
                shutil.copyfile(source_path, target_path)

            copied_item = dict(item)
            copied_item["source_local_path"] = str(source_path)
            copied_item["artifact_path"] = target_path.relative_to(case_dir).as_posix()
            copied.append(copied_item)
        return copied

    def _render_validation_issue_markdown(
        self,
        *,
        issue_payload: Dict[str, Any],
        screenshot_summary: List[Dict[str, Any]],
    ) -> str:
        lines = [
            "# Vision Validation Input",
            "",
            "## Issue",
            "",
            "```json",
            json.dumps(issue_payload, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Screenshot Manifest",
            "",
        ]
        if not screenshot_summary:
            lines.extend(["(empty)", ""])
            return "\n".join(lines).rstrip() + "\n"

        for index, item in enumerate(screenshot_summary, start=1):
            lines.extend([f"### Screenshot {index}", ""])
            if isinstance(item, dict):
                for key in (
                    "kind",
                    "page",
                    "bbox",
                    "page_bbox",
                    "matched_text",
                    "ocr_text",
                    "ocr_source",
                    "artifact_path",
                    "source_local_path",
                ):
                    value = item.get(key)
                    if value is None or value == "":
                        continue
                    lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}")
                artifact_path = str(item.get("artifact_path", "") or "").strip()
                if artifact_path:
                    lines.extend(["", f"![Screenshot {index}](../{artifact_path})", ""])
            else:
                lines.extend([str(item), ""])
        return "\n".join(lines).rstrip() + "\n"

    def _render_validation_request_markdown(
        self,
        *,
        issue_payload: Dict[str, Any],
        screenshot_summary: List[Dict[str, Any]],
        user_prompt: str,
    ) -> str:
        lines = [
            "# Vision Model Request",
            "",
            f"- model: {self.model_name}",
            "",
            "## Issue",
            "",
            "```json",
            json.dumps(issue_payload, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Images Sent To Model",
            "",
        ]
        if screenshot_summary:
            for index, item in enumerate(screenshot_summary, start=1):
                artifact_path = str(item.get("artifact_path", "") or "").strip()
                kind = str(item.get("kind", "") or "").strip()
                page = item.get("page")
                label = f"Screenshot {index}"
                if kind or page:
                    label += f" ({kind or 'image'} / page {page})"
                lines.append(f"- {label}")
                if artifact_path:
                    lines.append(f"  - file: `../{artifact_path}`")
            lines.append("")
        else:
            lines.extend(["(empty)", ""])

        lines.extend(
            [
                "## System Prompt",
                "",
                self.system_prompt.strip() or "(empty)",
                "",
                "## User Prompt",
                "",
                user_prompt.strip() or "(empty)",
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _write_json_file(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_markdown_file(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_text_file(path: Path, content: str) -> None:
        path.write_text(content if content else "", encoding="utf-8")

    def _call_llm(self, user_content: Any) -> LLMCallResult:
        if MOCK_MODE:
            mock_content = json.dumps(
                {
                    "decision": "keep",
                    "confidence": "medium",
                    "reason": "Mock vision validation result.",
                },
                ensure_ascii=False,
            )
            prompt_tokens = estimate_message_tokens(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_content},
                ]
            )
            return LLMCallResult(
                content=mock_content,
                elapsed_seconds=0.0,
                model="mock-vision-agent",
                prompt_tokens=prompt_tokens,
                completion_tokens=estimate_text_tokens(mock_content),
                total_tokens=prompt_tokens + estimate_text_tokens(mock_content),
                usage_source="estimated",
                request_chars=len(self.system_prompt) + len(str(user_content)),
                response_chars=len(mock_content),
                raw_usage={},
            )

        return self.client.complete(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=700,
            response_format={"type": "json_object"},
        )

    @staticmethod
    def _normalize_result(payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "decision": "review",
                "confidence": "low",
                "reason": f"Unexpected payload type: {type(payload).__name__}",
            }

        decision = str(payload.get("decision", "") or payload.get("verdict", "")).strip().lower()
        confidence = str(payload.get("confidence", "")).strip().lower()
        reason = str(payload.get("reason", "")).strip()

        decision_aliases = {
            "supported": "keep",
            "confirm": "keep",
            "confirmed": "keep",
            "valid": "keep",
            "reject": "drop",
            "rejected": "drop",
            "invalid": "drop",
            "uncertain": "review",
            "maybe": "review",
            "unknown": "review",
        }
        decision = decision_aliases.get(decision, decision)
        if decision not in {"keep", "drop", "review", "skip"}:
            decision = "review"
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        if not reason:
            reason = "No reason provided by the vision validator."
        if decision == "drop":
            reason_lower = reason.lower()
            uncertainty_markers = (
                "uncertain",
                "unsure",
                "not sure",
                "insufficient",
                "inconclusive",
                "ambiguous",
                "unclear",
                "cannot determine",
                "can't determine",
                "not enough",
            )
            if confidence != "high" or any(marker in reason_lower for marker in uncertainty_markers):
                decision = "review"
                confidence = "medium" if confidence == "high" else confidence
                reason = f"{reason} Downgraded to review because the screenshot evidence is not fully certain."

        return {
            "decision": decision,
            "confidence": confidence,
            "reason": reason,
        }
