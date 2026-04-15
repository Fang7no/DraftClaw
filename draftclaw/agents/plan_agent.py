"""
Plan Agent: understand one chunk and produce a structured review plan.
"""

import json
import os
from typing import Any, Dict, List, Optional

from agents.llm_utils import (
    ChatCompletionClient,
    LLMCallResult,
    estimate_message_tokens,
    estimate_text_tokens,
    extract_json_payload,
)
import config
from logger import AgentLogger
from prompt_loader import load_prompt_section_text, render_prompt_section_template


def _mock_mode_enabled() -> bool:
    return os.getenv("MOCK_MODE", "false").lower() == "true"


DEFAULT_SYSTEM_PROMPT = """You are DraftClaw's Plan Agent.

Read the current chunk carefully, explain where it sits in the paper, what it is doing,
what its core content is, what role figures/tables/formulas play, and produce targeted review questions.
Return JSON only."""


class PlanAgent:
    """Summarize a chunk into a structured plan for later agents."""

    def __init__(self, logger: Optional[AgentLogger] = None):
        self.logger = logger
        self.system_prompt = load_prompt_section_text(
            "plan_prompt.md",
            "system",
            fallback=DEFAULT_SYSTEM_PROMPT,
        )
        self.model_name = config.REVIEW_MODEL
        self.client = ChatCompletionClient(
            api_url=config.REVIEW_API_URL,
            api_key=config.REVIEW_API_KEY,
            model=self.model_name,
            default_timeout=90,
            max_retries=3,
        )

    def analyze(
        self,
        chunk_content: str,
        chunk_id: int,
        image_inputs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        image_inputs = list(image_inputs or [])
        active_images: List[Dict[str, Any]] = []

        if self.logger:
            self.logger.log(
                "PlanAgent",
                "input",
                chunk_id=chunk_id,
                input_data={
                    "chunk_content": chunk_content,
                    "image_inputs": self._summarize_images(active_images),
                },
                message="Building structured chunk plan",
            )
            self.logger.progress(
                "Plan Chunk",
                chunk_id=chunk_id,
                status="start",
                level=1,
                agent_name="PlanAgent",
                summary=f"images={len(active_images)}",
            )

        user_prompt = self._build_user_message(chunk_content, chunk_id)
        user_content = user_prompt
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            if self.logger:
                self.logger.log(
                    "PlanAgent",
                    "llm_input",
                    chunk_id=chunk_id,
                    data={
                        "model": self.model_name,
                        "prompt_tokens": estimate_message_tokens(messages),
                        "image_count": len(active_images),
                    },
                    input_data={"llm_messages": messages},
                    message="Calling planning model",
                )

            llm_result = self._call_llm(user_content)
            if self.logger:
                self.logger.log(
                    "PlanAgent",
                    "llm_output",
                    chunk_id=chunk_id,
                    data={"llm_metrics": llm_result.to_dict()},
                    output_data={"llm_output": llm_result.content},
                    message="Planning model raw output",
                )
            result = self._parse_response(llm_result.content)
            result = self._normalize_result(result)
            result["_llm_metrics"] = llm_result.to_dict()

            if self.logger:
                self.logger.log(
                    "PlanAgent",
                    "output",
                    chunk_id=chunk_id,
                    data={
                        "llm_metrics": llm_result.to_dict(),
                        "image_count": len(active_images),
                    },
                    input_data={
                        "user_message": user_prompt,
                        "image_inputs": self._summarize_images(active_images),
                    },
                    output_data=result,
                    message="Structured plan generated",
                )
                self.logger.progress(
                    "Plan Chunk",
                    chunk_id=chunk_id,
                    status="done",
                    level=1,
                    agent_name="PlanAgent",
                    summary=self._summarize_plan_result(result),
                )

            return result
        except Exception as exc:
            if self.logger:
                self.logger.log(
                    "PlanAgent",
                    "error",
                    chunk_id=chunk_id,
                    input_data={
                        "user_message": user_prompt,
                        "image_inputs": self._summarize_images(active_images),
                    },
                    message=f"Plan generation failed: {exc}",
                )
            raise

    def _build_user_message(self, chunk_content: str, chunk_id: int) -> str:
        return render_prompt_section_template(
            "plan_prompt.md",
            "user",
            fallback=(
                "Read the chunk and return JSON only with: section_role, chunk_purpose, "
                "core_content, visual_element_role, query_list.\n\n"
                "Chunk ID: {{chunk_id}}\n"
                "Chunk content:\n---\n{{chunk_content}}\n---\n"
            ),
            chunk_id=chunk_id,
            chunk_content=chunk_content,
        )

    def _call_llm(self, user_content: Any) -> LLMCallResult:
        if _mock_mode_enabled():
            mock_content = json.dumps(
                {
                    "section_role": "Method section",
                    "chunk_purpose": "Explain the method component in the current chunk.",
                    "core_content": "Defines the main method logic and its assumptions.",
                    "visual_element_role": "No figure, table, or formula is central in this chunk.",
                    "query_list": [
                        "Check whether the method steps are logically consistent.",
                        "Check whether the terminology stays consistent with other chunks.",
                        "Check whether any claim exceeds what the chunk actually supports.",
                    ],
                },
                ensure_ascii=False,
            )
            prompt_tokens = self.client_message_tokens(user_content)
            return LLMCallResult(
                content=mock_content,
                elapsed_seconds=0.0,
                model="mock-plan-agent",
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
            max_tokens=1200,
            response_format={"type": "json_object"},
        )

    def client_message_tokens(self, user_content: Any) -> int:
        return estimate_message_tokens(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ]
        )

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
    def _summarize_plan_result(result: Dict[str, Any]) -> str:
        query_list = result.get("query_list", [])
        preview = "; ".join(str(item).strip() for item in query_list[:2] if str(item).strip())
        if len(query_list) > 2:
            preview += "; ..."
        parts = [
            str(result.get("section_role", "")).strip()[:40],
            str(result.get("chunk_purpose", "")).strip()[:60],
        ]
        compact = " | ".join(part for part in parts if part)
        if preview:
            compact = f"{compact} | {preview}" if compact else preview
        return compact or "Structured plan ready"

    def _parse_response(self, response: str) -> Dict[str, Any]:
        payload = extract_json_payload(response)
        if not isinstance(payload, dict):
            raise ValueError(f"PlanAgent expected a JSON object, got: {type(payload).__name__}")
        return payload

    @staticmethod
    def _normalize_result(result: Dict[str, Any]) -> Dict[str, Any]:
        def normalize_text(key: str, fallback: str) -> str:
            value = str(result.get(key, "") or "").strip()
            return value or fallback

        query_list = result.get("query_list", [])
        if not isinstance(query_list, list):
            query_list = [query_list]

        normalized_queries = []
        for item in query_list:
            text = str(item or "").strip()
            if text and text not in normalized_queries:
                normalized_queries.append(text)

        if not normalized_queries:
            normalized_queries = [
                "Check whether the chunk's core claim is actually supported by its own evidence.",
                "Check whether this chunk stays consistent with nearby chunks and section intent.",
                "Check whether figures, tables, or formulas are interpreted correctly here.",
            ]

        return {
            "section_role": normalize_text("section_role", "Unclear section role in the paper."),
            "chunk_purpose": normalize_text("chunk_purpose", "Explain what the current chunk is doing."),
            "core_content": normalize_text("core_content", "Summarize the chunk's main content."),
            "visual_element_role": normalize_text(
                "visual_element_role",
                "No explicit figure, table, or formula role is evident in this chunk.",
            ),
            "query_list": normalized_queries[:6],
        }
