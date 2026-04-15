"""
Summary Agent: merge explore, search, and vision results into final issues.
"""

from __future__ import annotations

import ast
import json
import os
from typing import Any, Dict, List, Optional

from agents.llm_utils import (
    ChatCompletionClient,
    LLMRequestCancelled,
    LLMCallResult,
    estimate_message_tokens,
    estimate_text_tokens,
    extract_json_payload,
)
from bbox_locator import is_anchor_id, normalize_anchor_id
import config
from logger import AgentLogger
from prompt_loader import load_prompt_section_text, render_prompt_section_template


def _mock_mode_enabled() -> bool:
    return os.getenv("MOCK_MODE", "false").lower() == "true"


DEFAULT_SYSTEM_PROMPT = """You are DraftClaw's Summary Agent.

Merge explore, search, and vision outputs into final issues.
Do not invent issues. Preserve attached evidence metadata. Return JSON only."""


VALID_ISSUE_TYPES = {
    "Language Expression",
    "Background Knowledge",
    "Formula Computation",
    "Method Logic",
    "Experimental Operation",
    "Claim Distortion",
    "Citation Fabrication",
    "Context Misalignment",
    "Multimodal Inconsistency",
}
VALID_SEVERITIES = {"high", "medium", "low"}


class SummaryAgent:
    """Create final issue objects from staged candidate issues."""

    def __init__(self, logger: Optional[AgentLogger] = None):
        self.logger = logger
        self.system_prompt = load_prompt_section_text(
            "summary_prompt.md",
            "system",
            fallback=DEFAULT_SYSTEM_PROMPT,
        )
        self.model_name = config.REVIEW_MODEL
        self.client = ChatCompletionClient(
            api_url=config.REVIEW_API_URL,
            api_key=config.REVIEW_API_KEY,
            model=self.model_name,
            default_timeout=120,
            max_retries=3,
        )

    def summarize(
        self,
        *,
        chunk_id: int,
        plan_output: Dict[str, Any],
        explore_output: Dict[str, Any],
        candidate_issues: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if self.logger:
            self.logger.progress(
                "Summarize Findings",
                chunk_id=chunk_id,
                status="start",
                level=1,
                agent_name="SummaryAgent",
                summary=f"candidates={len(candidate_issues)}",
            )
            self.logger.log(
                "SummaryAgent",
                "input",
                chunk_id=chunk_id,
                input_data={
                    "plan_output": plan_output,
                    "explore_output": explore_output,
                    "candidate_issues": candidate_issues,
                },
                message="Starting summary merge",
            )

        if not candidate_issues:
            result = {"issues": [], "_llm_metrics": {}}
            if self.logger:
                self.logger.log(
                    "SummaryAgent",
                    "output",
                    chunk_id=chunk_id,
                    output_data=result,
                    message="No candidate issues to summarize",
                )
                self.logger.progress(
                    "Summarize Findings",
                    chunk_id=chunk_id,
                    status="done",
                    level=1,
                    agent_name="SummaryAgent",
                    summary="0 issues",
                )
            return result

        user_prompt = render_prompt_section_template(
            "summary_prompt.md",
            "user",
            fallback=(
                "Merge the candidate issues into final issues and return JSON.\n"
                "Candidates:\n{{candidate_issues_json}}"
            ),
            plan_json=json.dumps(plan_output, ensure_ascii=False, indent=2),
            explore_json=json.dumps(explore_output, ensure_ascii=False, indent=2),
            candidate_issues_json=json.dumps(candidate_issues, ensure_ascii=False, indent=2),
        )
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if self.logger:
            self.logger.log(
                "SummaryAgent",
                "llm_input",
                chunk_id=chunk_id,
                data={
                    "model": self.model_name,
                    "candidate_count": len(candidate_issues),
                    "prompt_tokens": estimate_message_tokens(messages),
                },
                input_data={"llm_messages": messages},
                message="Calling summary model",
            )

        try:
            llm_result = self._call_llm(user_prompt, candidate_issues)
            if self.logger:
                self.logger.log(
                    "SummaryAgent",
                    "llm_output",
                    chunk_id=chunk_id,
                    data={"llm_metrics": llm_result.to_dict()},
                    output_data={"llm_output": llm_result.content},
                    message="Summary model raw output",
                )
            payload = extract_json_payload(llm_result.content)
            if not isinstance(payload, dict):
                payload = {"issues": candidate_issues}

            issues = payload.get("issues", [])
            if not isinstance(issues, list):
                issues = candidate_issues

            normalized = self._normalize_issues(issues)
            final_issues = self._rehydrate_issues(normalized, candidate_issues)
            result = {
                "issues": self._deduplicate_issues(final_issues),
                "_llm_metrics": llm_result.to_dict(),
            }
        except LLMRequestCancelled:
            raise
        except Exception as exc:
            result = {
                "issues": self._deduplicate_issues(candidate_issues),
                "_llm_metrics": {
                    "fallback": True,
                    "error": str(exc),
                    "usage_source": "fallback",
                },
            }
            if self.logger:
                self.logger.log(
                    "SummaryAgent",
                    "output_fallback",
                    chunk_id=chunk_id,
                    input_data={
                        "candidate_issues": candidate_issues,
                    },
                    output_data=result,
                    message=f"Summary model did not complete; preserving {len(result['issues'])} candidate issues",
                )

        if self.logger:
            self.logger.log(
                "SummaryAgent",
                "output",
                chunk_id=chunk_id,
                data={"llm_metrics": result.get("_llm_metrics", {})},
                output_data=result,
                message=f"Summary produced {len(result['issues'])} issues",
            )
            self.logger.progress(
                "Summarize Findings",
                chunk_id=chunk_id,
                status="done",
                level=1,
                agent_name="SummaryAgent",
                summary=f"{len(result['issues'])} issues",
            )

        return result

    def _call_llm(self, user_prompt: str, candidate_issues: List[Dict[str, Any]]) -> LLMCallResult:
        if _mock_mode_enabled():
            content = json.dumps({"issues": candidate_issues}, ensure_ascii=False)
            token_count = estimate_text_tokens(content)
            return LLMCallResult(
                content=content,
                elapsed_seconds=0.0,
                model="mock-summary-agent",
                prompt_tokens=estimate_message_tokens(
                    [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                ),
                completion_tokens=token_count,
                total_tokens=token_count,
                usage_source="estimated",
                request_chars=len(self.system_prompt) + len(user_prompt),
                response_chars=len(content),
                raw_usage={},
            )

        return self.client.complete(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2400,
            response_format={"type": "json_object"},
        )

    @staticmethod
    def _normalize_anchor_like(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return normalize_anchor_id(text) if is_anchor_id(text) else text

    @classmethod
    def _normalize_issues(cls, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_type = str(issue.get("type", "")).strip()
            if issue_type not in VALID_ISSUE_TYPES:
                continue
            severity = str(issue.get("severity", "")).strip().lower()
            if severity not in VALID_SEVERITIES:
                severity = "medium"
            description = str(issue.get("description", "")).strip()
            evidence = issue.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = [evidence]
            evidence = [
                cls._normalize_anchor_like(item)
                for item in evidence
                if str(item).strip()
            ]
            location = cls._normalize_anchor_like(issue.get("location", ""))
            reasoning = cls._normalize_reasoning_field(issue.get("reasoning", ""))
            source_stage = str(issue.get("source_stage", "")).strip() or "local"

            if not description or not evidence:
                continue

            normalized.append(
                {
                    "type": issue_type,
                    "severity": severity,
                    "description": description,
                    "evidence": evidence[:4],
                    "location": location or evidence[0],
                    "reasoning": reasoning,
                    "source_stage": source_stage,
                    "search_result": issue.get("search_result"),
                    "vision_validation": issue.get("vision_validation"),
                }
            )
        return normalized

    @staticmethod
    def _normalize_reasoning_field(value: Any) -> str:
        items = value if isinstance(value, list) else None
        if items is None:
            text = str(value or "").strip()
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    parsed = None
                if isinstance(parsed, list):
                    items = parsed
        if items is None:
            items = [value]

        lines: List[str] = []
        for item in items:
            text = str(item or "").strip()
            if text:
                lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _match_key(issue: Dict[str, Any]) -> tuple[str, str, str]:
        location = SummaryAgent._normalize_anchor_like(issue.get("location", ""))
        return (
            str(issue.get("type", "")).strip().lower(),
            str(issue.get("description", "")).strip().lower(),
            location.strip().lower(),
        )

    def _rehydrate_issues(
        self,
        normalized: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        candidate_map = {self._match_key(issue): issue for issue in candidates if isinstance(issue, dict)}
        description_map = {
            (
                str(issue.get("type", "")).strip().lower(),
                str(issue.get("description", "")).strip().lower(),
            ): issue
            for issue in candidates
            if isinstance(issue, dict)
        }
        location_map = {
            (
                str(issue.get("type", "")).strip().lower(),
                self._normalize_anchor_like(issue.get("location", "")).strip().lower(),
            ): issue
            for issue in candidates
            if isinstance(issue, dict) and self._normalize_anchor_like(issue.get("location", "")).strip()
        }

        hydrated = []
        for issue in normalized:
            match = candidate_map.get(self._match_key(issue))
            if not match:
                match = description_map.get(
                    (
                        str(issue.get("type", "")).strip().lower(),
                        str(issue.get("description", "")).strip().lower(),
                    )
                )
            if not match:
                match = location_map.get(
                    (
                        str(issue.get("type", "")).strip().lower(),
                        str(issue.get("location", "")).strip().lower(),
                    )
                )
            merged = dict(match or {})
            merged.update(issue)
            hydrated.append(merged)
        return hydrated

    @staticmethod
    def _deduplicate_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()

        for issue in issues:
            fingerprint = (
                str(issue.get("type", "")).strip().lower(),
                str(issue.get("description", "")).strip().lower(),
                tuple(str(item).strip() for item in issue.get("evidence", []) if str(item).strip()),
                str(issue.get("chunk_id", "")).strip(),
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            deduped.append(issue)

        return deduped
