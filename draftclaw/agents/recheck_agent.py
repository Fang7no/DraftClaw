"""
Chunk-level recheck agent composed of text and vision validators.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agents.llm_utils import (
    ChatCompletionClient,
    LLMCallResult,
    estimate_message_tokens,
    estimate_text_tokens,
    extract_json_payload,
)
from agents.vision_agent import VisionValidationAgent
import config
from logger import AgentLogger
from pdf_screenshot import PDFIssueScreenshotRenderer
from prompt_loader import load_prompt_section_text, render_prompt_section_template


DEFAULT_RECHECK_SYSTEM_PROMPT = """You are DraftClaw's Text Recheck Agent.

Recheck all candidate issues from one chunk together against the full document text.
Return JSON only. Do not invent new issues."""

DEFAULT_RECHECK_USER_PROMPT = """Recheck these chunk issues against the full document text.

Full document text (`<current chunk>` marks the target chunk):
{{full_document_text}}

Issues:
{{issues_json}}"""

VALID_VISION_TYPES = {"Language Expression", "Formula Computation"}
VALID_DECISIONS = {"keep", "drop", "review", "skip"}
VALID_CONFIDENCE = {"high", "medium", "low"}
DROP_UNCERTAINTY_MARKERS = (
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
    "need more",
)


def _mock_mode_enabled() -> bool:
    return os.getenv("MOCK_MODE", "false").strip().lower() == "true"


def _normalize_decision(decision: Any) -> str:
    normalized = str(decision or "").strip().lower()
    aliases = {
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
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_DECISIONS:
        normalized = "review"
    return normalized


def _normalize_confidence(confidence: Any, *, default: str = "medium") -> str:
    normalized = str(confidence or "").strip().lower()
    if normalized not in VALID_CONFIDENCE:
        return default
    return normalized


def _normalize_reason(reason: Any, *, fallback: str) -> str:
    normalized = str(reason or "").strip()
    return normalized or fallback


def _force_conservative_decision(*, decision: str, confidence: str, reason: str) -> Dict[str, str]:
    if decision != "drop":
        return {
            "decision": decision,
            "confidence": confidence,
            "reason": reason,
        }

    reason_lower = reason.lower()
    if confidence == "high" and not any(marker in reason_lower for marker in DROP_UNCERTAINTY_MARKERS):
        return {
            "decision": decision,
            "confidence": confidence,
            "reason": reason,
        }

    return {
        "decision": "review",
        "confidence": "medium" if confidence == "high" else confidence,
        "reason": f"{reason} Downgraded to review because the drop evidence is not fully certain.",
    }


def _build_skip_result(*, reason: str, model: str = "") -> Dict[str, Any]:
    return {
        "validated": False,
        "decision": "skip",
        "confidence": "low",
        "reason": reason,
        "model": model,
    }


def _mark_current_chunk_context(document_text: str, chunk_text: str) -> str:
    overview = str(document_text or "")
    chunk = str(chunk_text or "").strip()
    if not overview.strip() or not chunk:
        return overview
    if "<current chunk>" in overview and "</current chunk>" in overview:
        return overview

    index = overview.find(chunk)
    match_length = len(chunk)
    if index < 0:
        probe = chunk[: min(len(chunk), 1200)].strip()
        if len(probe) < 80:
            return overview
        index = overview.find(probe)
        match_length = len(probe)
        if index < 0:
            return overview

    return (
        f"{overview[:index]}<current chunk>\n"
        f"{overview[index:index + match_length]}\n"
        f"</current chunk>{overview[index + match_length:]}"
    )


class TextRecheckAgent:
    """Recheck one chunk's final issues against the full document text."""

    def __init__(self, logger: Optional[AgentLogger] = None):
        self.logger = logger
        self.system_prompt = load_prompt_section_text(
            "recheck_text_prompt.md",
            "system",
            fallback=DEFAULT_RECHECK_SYSTEM_PROMPT,
        )
        self.model_name = config.RECHECK_LLM_MODEL
        self.client = ChatCompletionClient(
            api_url=config.RECHECK_LLM_API_URL,
            api_key=config.RECHECK_LLM_API_KEY,
            model=self.model_name,
            default_timeout=120,
            max_retries=3,
        )

    def validate_chunk(
        self,
        *,
        issues: Sequence[Dict[str, Any]],
        chunk_id: Optional[int],
        full_document_text: str,
        current_chunk_text: str,
    ) -> Dict[str, Any]:
        if not issues:
            return {"results": [], "_llm_metrics": {}}

        if not config.RECHECK_LLM_ENABLED:
            return {
                "results": [
                    _build_skip_result(
                        reason="Text recheck skipped because Recheck LLM is not configured.",
                        model=self.model_name,
                    )
                    for _ in issues
                ],
                "_llm_metrics": {},
            }

        issue_payloads = [
            {
                "issue_index": issue_index,
                "type": issue.get("type"),
                "severity": issue.get("severity"),
                "description": issue.get("description"),
                "evidence": issue.get("evidence"),
                "location": issue.get("location"),
                "reasoning": issue.get("reasoning"),
                "evidence_display": issue.get("evidence_display"),
                "location_display": issue.get("location_display"),
                "evidence_anchor_ids": issue.get("evidence_anchor_ids"),
                "location_anchor_ids": issue.get("location_anchor_ids"),
            }
            for issue_index, issue in enumerate(issues, start=1)
        ]
        marked_document_text = _mark_current_chunk_context(
            full_document_text,
            current_chunk_text,
        )
        user_prompt = render_prompt_section_template(
            "recheck_text_prompt.md",
            "user",
            fallback=DEFAULT_RECHECK_USER_PROMPT,
            full_document_text=marked_document_text,
            issues_json=json.dumps(issue_payloads, ensure_ascii=False, indent=2),
        )
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if self.logger:
            self.logger.log(
                "RecheckAgent",
                "text_input",
                chunk_id=chunk_id,
                data={
                    "model": self.model_name,
                    "issue_count": len(issue_payloads),
                    "prompt_tokens": estimate_message_tokens(messages),
                    "document_chars": len(marked_document_text),
                    "current_chunk_chars": len(str(current_chunk_text or "").strip()),
                    "current_chunk_marked": "<current chunk>" in marked_document_text,
                },
                input_data={
                    "chunk_id": chunk_id,
                    "full_document_preview": marked_document_text[:2000],
                    "full_document_chars": len(marked_document_text),
                    "issues": issue_payloads,
                },
                message="Starting chunk-level text recheck",
            )

        if _mock_mode_enabled():
            content = json.dumps(
                {
                    "issues": [
                        {
                            "issue_index": issue_index,
                            "decision": "keep",
                            "confidence": "medium",
                            "reason": "Mock text recheck kept the issue.",
                        }
                        for issue_index in range(1, len(issue_payloads) + 1)
                    ]
                },
                ensure_ascii=False,
            )
            llm_result = LLMCallResult(
                content=content,
                elapsed_seconds=0.0,
                model="mock-recheck-agent",
                prompt_tokens=estimate_message_tokens(messages),
                completion_tokens=estimate_text_tokens(content),
                total_tokens=estimate_message_tokens(messages) + estimate_text_tokens(content),
                usage_source="estimated",
                request_chars=len(self.system_prompt) + len(user_prompt),
                response_chars=len(content),
                raw_usage={},
            )
        else:
            llm_result = self.client.complete(
                messages,
                temperature=0.1,
                max_tokens=1600,
                response_format={"type": "json_object"},
            )

        normalized_results = self._normalize_chunk_results(
            extract_json_payload(llm_result.content),
            expected_issue_count=len(issue_payloads),
        )
        results = [
            {
                **result,
                "validated": result["decision"] != "skip",
                "model": self.model_name,
            }
            for result in normalized_results
        ]

        if self.logger:
            self.logger.log(
                "RecheckAgent",
                "text_output",
                chunk_id=chunk_id,
                data={"llm_metrics": llm_result.to_dict(), "issue_count": len(results)},
                output_data={"results": results},
                message="Chunk-level text recheck completed",
            )

        return {
            "results": results,
            "_llm_metrics": llm_result.to_dict(),
        }

    @classmethod
    def _normalize_result(cls, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}

        decision = _normalize_decision(payload.get("decision"))
        confidence = _normalize_confidence(payload.get("confidence"))
        reason = _normalize_reason(
            payload.get("reason"),
            fallback="No explicit text recheck rationale was provided.",
        )
        conservative_result = _force_conservative_decision(
            decision=decision,
            confidence=confidence,
            reason=reason,
        )
        return {
            "decision": conservative_result["decision"],
            "confidence": conservative_result["confidence"],
            "reason": conservative_result["reason"],
        }

    @classmethod
    def _normalize_chunk_results(
        cls,
        payload: Any,
        *,
        expected_issue_count: int,
    ) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            raw_results = payload
        elif isinstance(payload, dict):
            maybe_results = payload.get("issues") or payload.get("results")
            if isinstance(maybe_results, list):
                raw_results = maybe_results
            elif expected_issue_count == 1:
                raw_results = [payload]
            else:
                raw_results = []
        else:
            raw_results = []

        normalized_by_index: Dict[int, Dict[str, Any]] = {}
        for position, item in enumerate(raw_results, start=1):
            if not isinstance(item, dict):
                continue
            issue_index = item.get("issue_index", position)
            try:
                issue_key = int(issue_index)
            except (TypeError, ValueError):
                issue_key = position
            if issue_key < 1 or issue_key > expected_issue_count:
                continue
            normalized_by_index[issue_key] = cls._normalize_result(item)

        results: List[Dict[str, Any]] = []
        for issue_index in range(1, expected_issue_count + 1):
            results.append(
                normalized_by_index.get(
                    issue_index,
                    {
                        "decision": "review",
                        "confidence": "low",
                        "reason": "Chunk recheck did not return a usable decision for this issue.",
                    },
                )
            )
        return results


class RecheckAgent:
    """Run chunk-level text recheck and selective per-issue vision recheck."""

    def __init__(self, logger: Optional[AgentLogger] = None):
        self.logger = logger
        self.text_agent = TextRecheckAgent(logger=logger)
        self.vision_agent = VisionValidationAgent(logger=logger)

    @staticmethod
    def should_run_vision(issue_type: Any) -> bool:
        return str(issue_type or "").strip() in VALID_VISION_TYPES

    def recheck_chunk(
        self,
        *,
        issues: List[Dict[str, Any]],
        chunk_id: int,
        full_document_text: str,
        current_chunk_text: str,
        pdf_path: str,
        screenshots_dir: Path,
        text_enabled: bool,
        vision_enabled: bool,
    ) -> Dict[str, Any]:
        if not issues:
            return {
                "issues": [],
                "summary": self._empty_summary(),
                "llm_metrics_list": [],
                "vision_metrics_list": [],
            }

        renderer: Optional[PDFIssueScreenshotRenderer] = None
        if vision_enabled:
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            renderer = PDFIssueScreenshotRenderer(
                pdf_path,
                screenshots_dir,
                page_zoom=config.VISION_PAGE_ZOOM,
                crop_zoom=config.VISION_CROP_ZOOM,
                bbox_padding=config.VISION_BBOX_PADDING,
                max_matches=config.VISION_MAX_MATCH_IMAGES,
                bbox_normalized_size=config.BBOX_NORMALIZED_SIZE,
            )

        text_metrics: List[Dict[str, Any]] = []
        vision_metrics: List[Dict[str, Any]] = []
        summary = self._empty_summary()
        summary["total_input_issues"] = len(issues)
        summary["enabled"] = bool(text_enabled or vision_enabled)
        summary["text_enabled"] = bool(text_enabled)
        summary["vision_enabled"] = bool(vision_enabled)

        if self.logger:
            self.logger.progress(
                "Recheck",
                chunk_id=chunk_id,
                status="start",
                level=1,
                agent_name="RecheckAgent",
                summary=f"issues={len(issues)}",
            )

        if text_enabled:
            text_bundle = self.text_agent.validate_chunk(
                issues=issues,
                chunk_id=chunk_id,
                full_document_text=full_document_text,
                current_chunk_text=current_chunk_text,
            )
            text_results = list(text_bundle.get("results", []))
            text_metrics_payload = text_bundle.get("_llm_metrics", {})
            if text_metrics_payload:
                text_metrics.append(text_metrics_payload)
        else:
            text_results = [
                self._skip_text_result(reason="Text recheck is disabled for this run.")
                for _ in issues
            ]

        try:
            for issue_index, issue in enumerate(issues, start=1):
                text_validation = (
                    text_results[issue_index - 1]
                    if issue_index - 1 < len(text_results)
                    else {
                        "validated": False,
                        "decision": "review",
                        "confidence": "low",
                        "reason": "Missing text recheck output for this issue.",
                        "model": self.text_agent.model_name,
                    }
                )
                issue["text_validation"] = text_validation
                if text_validation.get("decision") != "skip":
                    summary["text_validated_issues"] += 1

                vision_validation = self._skip_vision_result(
                    reason="Vision recheck only applies to Language Expression and Formula Computation."
                )
                issue["vision_screenshots"] = []
                if vision_enabled and renderer and self.should_run_vision(issue.get("type")):
                    screenshots = renderer.render_issue(issue, issue_index)
                    issue["vision_screenshots"] = [
                        {
                            "kind": item.get("kind"),
                            "page": item.get("page"),
                            "bbox": item.get("bbox"),
                            "matched_text": item.get("matched_text"),
                            "ocr_text": item.get("ocr_text"),
                            "ocr_source": item.get("ocr_source"),
                            "local_path": item.get("local_path"),
                        }
                        for item in screenshots
                    ]
                    vision_validation = self.vision_agent.validate_issue(
                        issue=issue,
                        issue_index=issue_index,
                        chunk_id=chunk_id,
                        screenshots=screenshots,
                    )
                    vision_metrics_payload = vision_validation.pop("_llm_metrics", {})
                    if vision_metrics_payload:
                        vision_metrics.append(vision_metrics_payload)
                    if vision_validation.get("decision") != "skip":
                        summary["vision_validated_issues"] += 1
                elif not vision_enabled:
                    vision_validation = self._skip_vision_result(
                        reason="Vision recheck is disabled for this run."
                    )

                issue["vision_validation"] = vision_validation
                issue["recheck_validation"] = self._combine_decisions(
                    text_validation=issue["text_validation"],
                    vision_validation=issue["vision_validation"],
                )
                self._update_summary(summary, issue["recheck_validation"])
        finally:
            if renderer:
                renderer.close()

        summary["kept_issues"] = sum(
            1
            for issue in issues
            if str(issue.get("recheck_validation", {}).get("decision", "")).strip().lower() == "keep"
        )

        if self.logger:
            self.logger.log(
                "RecheckAgent",
                "chunk_output",
                chunk_id=chunk_id,
                data={"summary": summary},
                output_data={"issues": issues},
                message=f"Recheck completed for {len(issues)} issues",
            )
            self.logger.progress(
                "Recheck",
                chunk_id=chunk_id,
                status="done",
                level=1,
                agent_name="RecheckAgent",
                summary=(
                    f"keep={summary['kept_issues']} | drop={summary['dropped_issues']} | "
                    f"review={summary['review_issues']} | skip={summary['skipped_issues']}"
                ),
            )

        return {
            "issues": issues,
            "summary": summary,
            "llm_metrics_list": text_metrics + vision_metrics,
            "vision_metrics_list": vision_metrics,
        }

    @staticmethod
    def _skip_vision_result(*, reason: str) -> Dict[str, Any]:
        return {
            "validated": False,
            "decision": "skip",
            "confidence": "low",
            "reason": reason,
            "model": "",
            "screenshot_count": 0,
        }

    @staticmethod
    def _skip_text_result(*, reason: str) -> Dict[str, Any]:
        return _build_skip_result(reason=reason)

    @staticmethod
    def _empty_summary() -> Dict[str, Any]:
        return {
            "enabled": False,
            "text_enabled": False,
            "vision_enabled": False,
            "total_input_issues": 0,
            "text_validated_issues": 0,
            "vision_validated_issues": 0,
            "kept_issues": 0,
            "dropped_issues": 0,
            "review_issues": 0,
            "skipped_issues": 0,
        }

    @staticmethod
    def _update_summary(summary: Dict[str, Any], recheck_validation: Dict[str, Any]) -> None:
        decision = str(recheck_validation.get("decision", "") or "").strip().lower()
        if decision == "drop":
            summary["dropped_issues"] += 1
        elif decision == "review":
            summary["review_issues"] += 1
        elif decision == "skip":
            summary["skipped_issues"] += 1

    @staticmethod
    def _is_high_confidence_drop(result: Dict[str, Any]) -> bool:
        return (
            str(result.get("decision", "") or "").strip().lower() == "drop"
            and str(result.get("confidence", "") or "").strip().lower() == "high"
        )

    @classmethod
    def _combine_decisions(
        cls,
        *,
        text_validation: Dict[str, Any],
        vision_validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        text_decision = str(text_validation.get("decision", "") or "").strip().lower() or "skip"
        vision_decision = str(vision_validation.get("decision", "") or "").strip().lower() or "skip"
        decisions: Sequence[str] = [text_decision, vision_decision]
        text_drop = cls._is_high_confidence_drop(text_validation)
        vision_drop = cls._is_high_confidence_drop(vision_validation)

        if text_drop:
            if vision_decision == "skip" or vision_drop:
                decision = "drop"
                confidence = "high"
            else:
                decision = "review"
                confidence = "medium"
        elif vision_drop:
            if text_decision == "skip":
                decision = "drop"
                confidence = "high"
            else:
                decision = "review"
                confidence = "medium"
        elif "review" in decisions:
            decision = "review"
            confidence = "medium"
        elif "keep" in decisions:
            decision = "keep"
            confidence = "medium" if vision_decision == "skip" else "high"
        else:
            decision = "skip"
            confidence = "low"

        reasons = []
        text_reason = str(text_validation.get("reason", "") or "").strip()
        vision_reason = str(vision_validation.get("reason", "") or "").strip()
        if text_reason:
            reasons.append(f"Text: {text_reason}")
        if vision_decision != "skip" and vision_reason:
            reasons.append(f"Vision: {vision_reason}")
        if not reasons:
            reasons.append("No recheck rationale was recorded.")

        return {
            "validated": decision != "skip",
            "decision": decision,
            "confidence": confidence,
            "reason": " ".join(reasons),
            "model": "aggregate",
            "agents_run": {
                "text": text_decision != "skip",
                "vision": vision_decision != "skip",
            },
        }
