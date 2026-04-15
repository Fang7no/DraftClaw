"""
Explore Agent: run local check, global check, then finalize one chunk's error list.
"""

import ast
import json
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional

from agents.llm_utils import (
    ChatCompletionClient,
    LLMCallResult,
    estimate_message_tokens,
    estimate_text_tokens,
    extract_json_payload,
)
from bbox_locator import is_anchor_id, normalize_anchor_id
import config
from logger import AgentLogger
from prompt_loader import render_prompt_section_template


def _mock_mode_enabled() -> bool:
    return os.getenv("MOCK_MODE", "false").lower() == "true"


DEFAULT_SYSTEM_PROMPT = """You are DraftClaw's Explore Agent.

Follow the fixed order: local check, global check, final consolidation.
Only output real, well-supported issues. Return JSON only."""

EXPLORE_PROMPT_FILES = {
    "local_initial": "explore/local_initial_prompt.md",
    "local_finalize": "explore/local_finalize_prompt.md",
    "global_initial": "explore/global_initial_prompt.md",
    "global_finalize": "explore/global_finalize_prompt.md",
    "merge": "explore/merge_prompt.md",
}


VALID_ISSUE_TYPES = {
    "Language Expression",
    "Background Knowledge",
    "Formula Computation",
    "Method Logic",
    "Experimental Operation",
    "Claim Distortion",
    "Citation Fabrication",
    "Context Misalignment",
}

VALID_SEVERITIES = {"high", "medium", "low"}
VALID_SOURCE_STAGES = {"local", "global", "local+global"}

NON_ISSUE_MARKERS = [
    "is consistent",
    "are consistent",
    "no contradiction",
    "does not conflict",
    "citation is appropriate",
    "well-supported",
    "not a real issue",
]

SENTENCE_HINT_PATTERN = re.compile(r"[。！？!?；;]")


class ExploreAgent:
    """Produce staged issue lists for the current chunk."""

    def __init__(self, logger: Optional[AgentLogger] = None):
        self.logger = logger
        self.model_name = config.REVIEW_MODEL
        self.client = ChatCompletionClient(
            api_url=config.REVIEW_API_URL,
            api_key=config.REVIEW_API_KEY,
            model=self.model_name,
            default_timeout=120,
            max_retries=3,
        )

    def explore(
        self,
        *,
        chunk_id: int,
        chunk_content: str,
        document_overview: str,
        global_chunk_map: str,
        neighbor_context: str,
        plan_output: Dict[str, Any],
        image_inputs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        image_inputs = list(image_inputs or [])
        active_images: List[Dict[str, Any]] = []
        plan_summary = str(plan_output.get("chunk_purpose", "") or "").strip()[:80] or "plan ready"

        if self.logger:
            self.logger.log(
                "ExploreAgent",
                "stage_local_input",
                chunk_id=chunk_id,
                input_data={
                    "plan_output": plan_output,
                    "chunk_content": chunk_content,
                    "image_inputs": self._summarize_images(active_images),
                },
                message="Starting local check",
            )
            self.logger.progress(
                "Local Check",
                chunk_id=chunk_id,
                status="start",
                level=1,
                agent_name="ExploreAgent",
                summary=plan_summary,
            )

        local_stage = self.run_local_initial(
            chunk_id=chunk_id,
            chunk_content=chunk_content,
            plan_output=plan_output,
            image_inputs=active_images,
        )
        local_result = local_stage.get("local_error_list", [])
        local_search_requests = local_stage.get("search_requests", [])
        local_metrics = local_stage.get("_llm_metrics", {})

        if self.logger:
            self.logger.log(
                "ExploreAgent",
                "stage_local_output",
                chunk_id=chunk_id,
                data={"llm_metrics": local_metrics},
                output_data={
                    "local_error_list": local_result,
                    "search_requests": local_search_requests,
                },
                message=f"Local check produced {len(local_result)} issues",
            )
            self.logger.progress(
                "Local Check",
                chunk_id=chunk_id,
                status="done",
                level=1,
                agent_name="ExploreAgent",
                summary=self._summarize_issues(local_result),
            )
            self.logger.progress(
                "Global Check",
                chunk_id=chunk_id,
                status="start",
                level=1,
                agent_name="ExploreAgent",
                summary=f"local={len(local_result)}",
            )

        global_document_overview = self._mark_current_chunk_context(
            document_overview,
            chunk_content,
        )

        global_stage = self.run_global_initial(
            chunk_id=chunk_id,
            document_overview=global_document_overview,
            image_inputs=active_images,
        )
        global_result = global_stage.get("global_error_list", [])
        global_search_requests = global_stage.get("search_requests", [])
        global_metrics = global_stage.get("_llm_metrics", {})

        if self.logger:
            self.logger.log(
                "ExploreAgent",
                "stage_global_output",
                chunk_id=chunk_id,
                data={"llm_metrics": global_metrics},
                output_data={
                    "global_error_list": global_result,
                    "search_requests": global_search_requests,
                },
                message=f"Global check produced {len(global_result)} issues",
            )
            self.logger.progress(
                "Global Check",
                chunk_id=chunk_id,
                status="done",
                level=1,
                agent_name="ExploreAgent",
                summary=self._summarize_issues(global_result),
            )
            self.logger.progress(
                "Finalize ErrorList",
                chunk_id=chunk_id,
                status="start",
                level=1,
                agent_name="ExploreAgent",
                summary=f"local={len(local_result)} | global={len(global_result)}",
            )

        merge_stage = self.merge_error_lists(
            chunk_id=chunk_id,
            plan_output=plan_output,
            local_error_list=local_result,
            global_error_list=global_result,
            image_inputs=active_images,
        )
        final_result = merge_stage.get("error_list", [])
        final_metrics = merge_stage.get("_llm_metrics", {})

        if self.logger:
            self.logger.log(
                "ExploreAgent",
                "stage_final_output",
                chunk_id=chunk_id,
                data={"llm_metrics": final_metrics},
                output_data={"error_list": final_result},
                message=f"Final ErrorList contains {len(final_result)} issues",
            )
            self.logger.progress(
                "Finalize ErrorList",
                chunk_id=chunk_id,
                status="done",
                level=1,
                agent_name="ExploreAgent",
                summary=self._summarize_issues(final_result),
            )

        return {
            "local_error_list": local_result,
            "global_error_list": global_result,
            "final_error_list": final_result,
            "error_list": final_result,
            "local_search_requests": local_search_requests,
            "global_search_requests": global_search_requests,
            "_llm_metrics_list": [local_metrics, global_metrics, final_metrics],
        }

    def run_local_initial(
        self,
        *,
        chunk_id: int,
        chunk_content: str,
        plan_output: Dict[str, Any],
        image_inputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        user_prompt = render_prompt_section_template(
            EXPLORE_PROMPT_FILES["local_initial"],
            "user",
            fallback=(
                "Run a local check on the current chunk and return JSON with local_error_list.\n"
                "Chunk:\n{{chunk_content}}"
            ),
            plan_markdown=self._render_plan_markdown(plan_output),
            chunk_content=chunk_content,
            current_date_text=self._current_date_text(),
        )
        payload, llm_metrics = self._call_stage(
            stage_name="local_initial",
            user_prompt=user_prompt,
            image_inputs=image_inputs,
            default_payload={"local_error_list": [], "search_requests": []},
        )
        issues = payload.get("local_error_list", [])
        if not isinstance(issues, list):
            issues = []
        return {
            "local_error_list": self._post_process_issues(issues, default_stage="local"),
            "search_requests": self._normalize_search_requests(
                payload.get("search_requests", []),
                prefix="local",
            ),
            "_llm_metrics": llm_metrics,
        }

    def run_local_finalize(
        self,
        *,
        chunk_id: int,
        chunk_content: str,
        plan_output: Dict[str, Any],
        local_error_list: List[Dict[str, Any]],
        search_requests: List[Dict[str, Any]],
        search_results: List[Dict[str, Any]],
        image_inputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        user_prompt = render_prompt_section_template(
            EXPLORE_PROMPT_FILES["local_finalize"],
            "user",
            fallback=(
                "Finalize the local issue list with search results and return JSON with local_error_list.\n"
            ),
            plan_markdown=self._render_plan_markdown(plan_output),
            chunk_content=chunk_content,
            local_error_list_json=json.dumps(local_error_list, ensure_ascii=False, indent=2),
            search_requests_json=json.dumps(search_requests, ensure_ascii=False, indent=2),
            search_results_json=json.dumps(search_results, ensure_ascii=False, indent=2),
            current_date_text=self._current_date_text(),
        )
        payload, llm_metrics = self._call_stage(
            stage_name="local_finalize",
            user_prompt=user_prompt,
            image_inputs=image_inputs,
            default_payload={"local_error_list": []},
        )
        issues = payload.get("local_error_list", [])
        if not isinstance(issues, list):
            issues = []
        return {
            "local_error_list": self._post_process_issues(issues, default_stage="local"),
            "_llm_metrics": llm_metrics,
        }

    def run_global_initial(
        self,
        *,
        chunk_id: int,
        document_overview: str,
        image_inputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        user_prompt = render_prompt_section_template(
            EXPLORE_PROMPT_FILES["global_initial"],
            "user",
            fallback=(
                "Run a global check and return JSON with global_error_list.\n"
                "Marked full document context:\n{{document_overview}}"
            ),
            document_overview=document_overview,
            current_date_text=self._current_date_text(),
        )
        payload, llm_metrics = self._call_stage(
            stage_name="global_initial",
            user_prompt=user_prompt,
            image_inputs=image_inputs,
            default_payload={"global_error_list": [], "search_requests": []},
        )
        issues = payload.get("global_error_list", [])
        if not isinstance(issues, list):
            issues = []
        return {
            "global_error_list": self._post_process_issues(issues, default_stage="global"),
            "search_requests": self._normalize_search_requests(
                payload.get("search_requests", []),
                prefix="global",
            ),
            "_llm_metrics": llm_metrics,
        }

    def run_global_finalize(
        self,
        *,
        chunk_id: int,
        document_overview: str,
        global_error_list: List[Dict[str, Any]],
        search_requests: List[Dict[str, Any]],
        search_results: List[Dict[str, Any]],
        image_inputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        user_prompt = render_prompt_section_template(
            EXPLORE_PROMPT_FILES["global_finalize"],
            "user",
            fallback=(
                "Finalize the global issue list with search results and return JSON with global_error_list.\n"
            ),
            document_overview=document_overview,
            global_error_list_json=json.dumps(global_error_list, ensure_ascii=False, indent=2),
            search_requests_json=json.dumps(search_requests, ensure_ascii=False, indent=2),
            search_results_json=json.dumps(search_results, ensure_ascii=False, indent=2),
            current_date_text=self._current_date_text(),
        )
        payload, llm_metrics = self._call_stage(
            stage_name="global_finalize",
            user_prompt=user_prompt,
            image_inputs=image_inputs,
            default_payload={"global_error_list": []},
        )
        issues = payload.get("global_error_list", [])
        if not isinstance(issues, list):
            issues = []
        return {
            "global_error_list": self._post_process_issues(issues, default_stage="global"),
            "_llm_metrics": llm_metrics,
        }

    def merge_error_lists(
        self,
        *,
        chunk_id: int,
        plan_output: Dict[str, Any],
        local_error_list: List[Dict[str, Any]],
        global_error_list: List[Dict[str, Any]],
        image_inputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        user_prompt = render_prompt_section_template(
            EXPLORE_PROMPT_FILES["merge"],
            "user",
            fallback=(
                "Merge the local and global issue lists and return JSON with error_list.\n"
            ),
            plan_json=json.dumps(plan_output, ensure_ascii=False, indent=2),
            local_error_list_json=json.dumps(local_error_list, ensure_ascii=False, indent=2),
            global_error_list_json=json.dumps(global_error_list, ensure_ascii=False, indent=2),
            current_date_text=self._current_date_text(),
        )
        payload, llm_metrics = self._call_stage(
            stage_name="merge",
            user_prompt=user_prompt,
            image_inputs=image_inputs,
            default_payload={"error_list": []},
        )
        issues = payload.get("error_list", payload.get("final_error_list", []))
        if not isinstance(issues, list):
            issues = []
        normalized = self._post_process_issues(issues, default_stage="local+global")
        return {
            "error_list": self._merge_stage_context(normalized, local_error_list, global_error_list),
            "_llm_metrics": llm_metrics,
        }

    def _call_stage(
        self,
        *,
        stage_name: str,
        user_prompt: str,
        image_inputs: List[Dict[str, Any]],
        default_payload: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        image_inputs = []
        system_prompt = self._render_system_prompt(stage_name)
        user_content = user_prompt
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        if self.logger:
            self.logger.log(
                "ExploreAgent",
                f"stage_{stage_name}_llm_input",
                data={
                    "model": self.model_name,
                    "prompt_tokens": estimate_message_tokens(messages),
                    "image_count": len(image_inputs),
                },
                input_data={"llm_messages": messages},
                message=f"Calling explore model for {stage_name} check",
            )

        if _mock_mode_enabled():
            mock_content = json.dumps(default_payload, ensure_ascii=False)
            llm_result = LLMCallResult(
                content=mock_content,
                elapsed_seconds=0.0,
                model="mock-explore-agent",
                prompt_tokens=0,
                completion_tokens=estimate_text_tokens(mock_content),
                total_tokens=estimate_text_tokens(mock_content),
                usage_source="estimated",
                request_chars=len(system_prompt) + len(str(user_content)),
                response_chars=len(mock_content),
                raw_usage={},
            )
            if self.logger:
                self.logger.log(
                    "ExploreAgent",
                    f"stage_{stage_name}_llm_output",
                    data={"llm_metrics": llm_result.to_dict()},
                    output_data={"llm_output": llm_result.content},
                    message=f"Explore model raw output for {stage_name}",
                )
            return default_payload, llm_result.to_dict()

        llm_result = self.client.complete(
            messages,
            temperature=0.1,
            max_tokens=2200,
            response_format={"type": "json_object"},
        )
        if self.logger:
            self.logger.log(
                "ExploreAgent",
                f"stage_{stage_name}_llm_output",
                data={"llm_metrics": llm_result.to_dict()},
                output_data={"llm_output": llm_result.content},
                message=f"Explore model raw output for {stage_name}",
            )

        payload = extract_json_payload(llm_result.content)
        if not isinstance(payload, dict):
            raise ValueError(
                f"ExploreAgent expected a JSON object in {stage_name} stage, got: {type(payload).__name__}"
            )
        return payload, llm_result.to_dict()

    def _render_system_prompt(self, stage_name: str) -> str:
        prompt_file = EXPLORE_PROMPT_FILES.get(stage_name)
        if not prompt_file:
            return DEFAULT_SYSTEM_PROMPT
        return render_prompt_section_template(
            prompt_file,
            "system",
            fallback=DEFAULT_SYSTEM_PROMPT,
            current_date_text=self._current_date_text(),
        )

    @staticmethod
    def _mark_current_chunk_context(document_overview: str, chunk_content: str) -> str:
        overview = str(document_overview or "")
        chunk = str(chunk_content or "").strip()
        if not overview.strip() or not chunk:
            return overview
        if "<current chunk>" in overview and "</current chunk>" in overview:
            return overview
        index = overview.find(chunk)
        if index < 0:
            return overview
        return (
            f"{overview[:index]}<current chunk>\n"
            f"{overview[index:index + len(chunk)]}\n"
            f"</current chunk>{overview[index + len(chunk):]}"
        )

    @staticmethod
    def _render_plan_markdown(plan_output: Dict[str, Any]) -> str:
        fields = [
            ("section_role", "section_role"),
            ("chunk_purpose", "chunk_purpose"),
            ("core_content", "core_content"),
            ("visual_element_role", "visual_element_role"),
        ]
        lines = []
        for key, label in fields:
            value = str(plan_output.get(key, "") or "").strip() or "N/A"
            lines.append(f"- {label}: {value}")
        return "\n".join(lines)

    @staticmethod
    def _current_date_text() -> str:
        return date.today().isoformat()

    @staticmethod
    def _normalize_search_requests(value: Any, *, prefix: str) -> List[Dict[str, str]]:
        items = value if isinstance(value, list) else [value]
        normalized: List[Dict[str, str]] = []
        seen = set()

        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                request_id = str(item.get("request_id", "") or "").strip()
                goal = str(item.get("goal", "") or item.get("search_intent", "") or "").strip()
                query = str(
                    item.get("query", "")
                    or item.get("search_query", "")
                    or item.get("request", "")
                    or ""
                ).strip()
            else:
                request_id = ""
                goal = ""
                query = str(item or "").strip()

            if not query:
                continue
            if not request_id:
                request_id = f"{prefix}-{index}"
            if not goal:
                goal = query

            fingerprint = (goal.lower(), query.lower())
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            normalized.append(
                {
                    "request_id": request_id,
                    "goal": goal,
                    "query": query,
                }
            )

        return normalized[:6]

    def _post_process_issues(
        self,
        issues: List[Dict[str, Any]],
        *,
        default_stage: str,
    ) -> List[Dict[str, Any]]:
        normalized_map: Dict[tuple[str, str, str], Dict[str, Any]] = {}

        for raw_issue in issues:
            if not isinstance(raw_issue, dict):
                continue

            issue_type = str(raw_issue.get("type", "")).strip()
            severity = str(raw_issue.get("severity", "")).strip().lower()
            description = str(raw_issue.get("description", "")).strip()
            evidence = self._normalize_evidence_field(raw_issue.get("evidence", ""))
            location = self._normalize_sentence_field(raw_issue.get("location", ""))
            reasoning = self._normalize_reasoning_field(raw_issue.get("reasoning", ""))
            source_stage = str(raw_issue.get("source_stage", "")).strip().lower() or default_stage

            if issue_type not in VALID_ISSUE_TYPES:
                continue
            if issue_type == "Multimodal Inconsistency":
                continue
            if severity not in VALID_SEVERITIES:
                severity = "medium"
            if source_stage not in VALID_SOURCE_STAGES:
                source_stage = default_stage
            if not description or not evidence:
                continue
            if not location:
                location = evidence[0]
            if self._looks_like_non_issue(description, reasoning):
                continue

            fingerprint = (issue_type, description, location or "Current chunk")
            existing = normalized_map.get(fingerprint)
            if existing:
                existing["evidence"] = self._merge_evidence_lists(existing["evidence"], evidence)
                if self._severity_rank(severity) > self._severity_rank(existing.get("severity", "medium")):
                    existing["severity"] = severity
                if len(reasoning) > len(str(existing.get("reasoning", ""))):
                    existing["reasoning"] = reasoning
                existing["source_stage"] = self._merge_source_stage(
                    existing.get("source_stage", default_stage),
                    source_stage,
                )
                continue

            normalized_map[fingerprint] = {
                "type": issue_type,
                "severity": severity,
                "description": description,
                "evidence": evidence,
                "location": location or "Current chunk",
                "reasoning": reasoning,
                "source_stage": source_stage,
            }

        return list(normalized_map.values())[:8]

    def _merge_stage_context(
        self,
        final_issues: List[Dict[str, Any]],
        local_issues: List[Dict[str, Any]],
        global_issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        local_descriptions = {str(item.get("description", "")).strip().lower() for item in local_issues}
        global_descriptions = {str(item.get("description", "")).strip().lower() for item in global_issues}

        merged = []
        for issue in final_issues:
            description_key = str(issue.get("description", "")).strip().lower()
            in_local = description_key in local_descriptions
            in_global = description_key in global_descriptions
            if in_local and in_global:
                issue["source_stage"] = "local+global"
            elif in_local:
                issue["source_stage"] = "local"
            elif in_global:
                issue["source_stage"] = "global"
            merged.append(issue)
        return merged

    @staticmethod
    def _normalize_sentence_field(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = text.strip("\"'`")
        if not text:
            return ""
        anchor_candidate = text.split("|", 1)[0].strip().strip("`")
        if is_anchor_id(anchor_candidate):
            return normalize_anchor_id(anchor_candidate)
        if not SENTENCE_HINT_PATTERN.search(text) and text.lower().startswith(
            ("section ", "fig", "table ", "equation ")
        ):
            return ""
        return text

    @classmethod
    def _normalize_evidence_field(cls, value: Any) -> List[str]:
        items = value if isinstance(value, list) else [value]
        normalized: List[str] = []
        seen = set()
        for item in items:
            text = cls._normalize_sentence_field(item)
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized[:4]

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
    def _merge_evidence_lists(left: List[str], right: List[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for item in list(left) + list(right):
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
        return merged[:4]

    @staticmethod
    def _merge_source_stage(left: str, right: str) -> str:
        stages = {str(left or "").strip().lower(), str(right or "").strip().lower()}
        if "local+global" in stages or stages == {"local", "global"}:
            return "local+global"
        if "global" in stages:
            return "global"
        return "local"

    @staticmethod
    def _severity_rank(value: str) -> int:
        return {"low": 0, "medium": 1, "high": 2}.get(str(value or "").strip().lower(), 1)

    @staticmethod
    def _looks_like_non_issue(description: str, reasoning: str) -> bool:
        combined = f"{description}\n{reasoning}".lower()
        return any(marker.lower() in combined for marker in NON_ISSUE_MARKERS)

    @staticmethod
    def _summarize_images(image_inputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        summary = []
        for image in image_inputs:
            summary.append(
                {
                    "img_path": image.get("img_path"),
                    "page_idx": image.get("page_idx"),
                    "local_path": image.get("local_path"),
                    "merged_image_count": image.get("merged_image_count", 1),
                    "source_image_paths": image.get("source_image_paths", []),
                    "caption": " ".join(
                        str(item).strip()
                        for item in image.get("image_caption", [])
                        if str(item).strip()
                    )[:300],
                }
            )
        return summary

    @staticmethod
    def _summarize_issues(issues: List[Dict[str, Any]]) -> str:
        if not issues:
            return "0 issues"
        labels = ", ".join(
            f"{issue.get('type', '?')}/{issue.get('severity', '?')}" for issue in issues[:3]
        )
        if len(issues) > 3:
            labels += ", ..."
        return f"{len(issues)} issues | {labels}"
