"""
Language switching utilities for the final review report.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
import time
from typing import Any, Dict, Iterable, List, Tuple

from agents.llm_utils import ChatCompletionClient, extract_json_payload
import config
from prompt_loader import render_prompt_section_template


TRANSLATABLE_FIELDS = (
    "type",
    "severity",
    "description",
    "reasoning",
)

ISSUE_KEY_FIELDS = {
    "type": "type_key",
    "severity": "severity_key",
}

ORIGINAL_FIELD_SUFFIX = "_original"


def normalize_report_language(language: str) -> str:
    normalized = str(language or "").strip().lower().replace("_", "-")
    mapping = {
        "zh": "zh",
        "zh-cn": "zh",
        "cn": "zh",
        "chinese": "zh",
        "中文": "zh",
        "简体中文": "zh",
        "en": "en",
        "en-us": "en",
        "en-gb": "en",
        "english": "en",
        "英文": "en",
    }
    return mapping.get(normalized, "zh")


def language_display_name(language: str) -> str:
    return {"zh": "Simplified Chinese", "en": "English"}.get(
        normalize_report_language(language),
        "Simplified Chinese",
    )


def detect_text_language(text: str) -> str:
    cjk_chars = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))
    latin_words = len(re.findall(r"\b[a-zA-Z]{2,}\b", text))
    if cjk_chars == 0 and latin_words == 0:
        return "unknown"
    if cjk_chars >= max(16, int(latin_words * 1.1)):
        return "zh"
    if latin_words >= max(12, int(cjk_chars / 2)):
        return "en"
    return "unknown"


def aggregate_llm_metrics(metrics_list: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    metrics_items = [metrics for metrics in metrics_list if isinstance(metrics, dict) and metrics]
    usage_sources = sorted(
        {
            str(metrics.get("usage_source", "")).strip()
            for metrics in metrics_items
            if str(metrics.get("usage_source", "")).strip()
        }
    )
    return {
        "llm_calls": len(metrics_items),
        "elapsed_seconds": round(
            sum(float(metrics.get("elapsed_seconds", 0.0) or 0.0) for metrics in metrics_items),
            3,
        ),
        "prompt_tokens": sum(int(metrics.get("prompt_tokens", 0) or 0) for metrics in metrics_items),
        "completion_tokens": sum(int(metrics.get("completion_tokens", 0) or 0) for metrics in metrics_items),
        "total_tokens": sum(int(metrics.get("total_tokens", 0) or 0) for metrics in metrics_items),
        "usage_source": ",".join(usage_sources),
    }


class ReportLanguageSwitchAgent:
    """Translate human-readable review report fields into the selected language."""

    def __init__(
        self,
        *,
        target_language: str,
        logger: Any | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        batch_chars: int | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.target_language = normalize_report_language(target_language)
        self.logger = logger
        self.batch_chars = max(1200, int(batch_chars or config.REPORT_TRANSLATION_BATCH_CHARS))
        self.max_tokens = max(512, int(max_tokens or config.REPORT_TRANSLATION_MAX_TOKENS))
        self.model = str(model or config.TRANSLATION_MODEL or "").strip()
        self.client = ChatCompletionClient(
            api_url=api_url or config.TRANSLATION_API_URL,
            api_key=api_key or config.TRANSLATION_API_KEY,
            model=self.model,
        )

    def switch_report(self, report_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        started_at = time.perf_counter()
        report_copy = deepcopy(report_data)
        issues = report_copy.get("issues", [])

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            for field_name, key_name in ISSUE_KEY_FIELDS.items():
                issue.setdefault(key_name, str(issue.get(field_name, "") or ""))

        detected_language = self.detect_report_language(report_copy)
        switch_needed = detected_language != self.target_language and bool(issues)

        if self.logger:
            self.logger.log(
                "LanguageSwitchAgent",
                "detect",
                data={
                    "detected_language": detected_language,
                    "target_language": self.target_language,
                    "issue_count": len(issues),
                    "switch_needed": switch_needed,
                },
                message="Detected review report language",
            )

        translation_metrics: List[Dict[str, Any]] = []
        translated_issue_count = 0
        translation_error_count = 0

        if switch_needed:
            for batch_index, batch in enumerate(self._build_issue_batches(issues), start=1):
                batch_ids = [int(issue.get("_translation_id", issue.get("id", 0)) or 0) for issue in batch]
                messages = self._build_messages(batch)
                if self.logger:
                    self.logger.log(
                        "LanguageSwitchAgent",
                        "llm_input",
                        data={
                            "model": self.model,
                            "batch_index": batch_index,
                            "batch_issue_ids": batch_ids,
                            "issue_count": len(batch),
                        },
                        input_data={"llm_messages": messages},
                        message=f"Translating report batch {batch_index}",
                    )

                try:
                    llm_result = self.client.complete(
                        messages,
                        temperature=0.1,
                        max_tokens=self.max_tokens,
                        response_format={"type": "json_object"},
                    )
                    translation_metrics.append(llm_result.to_dict())
                    if self.logger:
                        self.logger.log(
                            "LanguageSwitchAgent",
                            "llm_output",
                            data={
                                "batch_index": batch_index,
                                "issue_count": len(batch),
                                "llm_metrics": llm_result.to_dict(),
                            },
                            output_data={"llm_output": llm_result.content},
                            message=f"Translation model raw output for batch {batch_index}",
                        )
                    translated_payload = extract_json_payload(llm_result.content)
                    translated_items = translated_payload.get("items", []) if isinstance(translated_payload, dict) else []
                    translated_map = {
                        int(item.get("id", 0)): item
                        for item in translated_items
                        if isinstance(item, dict) and int(item.get("id", 0) or 0) > 0
                    }
                except Exception as exc:
                    translation_error_count += 1
                    if self.logger:
                        self.logger.log(
                            "LanguageSwitchAgent",
                            "translation_batch_error",
                            data={
                                "batch_index": batch_index,
                                "issue_count": len(batch),
                                "batch_issue_ids": batch_ids,
                                "error_type": type(exc).__name__,
                            },
                            output_data={"error": str(exc)},
                            message=f"Translation batch {batch_index} failed; preserving original issue text",
                        )
                    continue

                for issue in batch:
                    translation_id = int(issue.get("_translation_id", issue.get("id", 0)) or 0)
                    translated_item = translated_map.get(translation_id)
                    if not translated_item:
                        continue
                    translated_issue_count += 1
                    self._apply_issue_translation(issue, translated_item)

                if self.logger:
                    self.logger.log(
                        "LanguageSwitchAgent",
                        "output",
                        data={
                            "batch_index": batch_index,
                            "issue_count": len(batch),
                            "translated_issue_count": len(translated_map),
                            "llm_metrics": llm_result.to_dict(),
                        },
                        output_data={"translated_ids": sorted(translated_map)},
                        message=f"Translated report batch {batch_index}",
                    )

        for issue in issues:
            if isinstance(issue, dict):
                issue.pop("_translation_id", None)

        aggregate_metrics = aggregate_llm_metrics(translation_metrics)
        metadata = {
            "target_language": self.target_language,
            "target_language_display": language_display_name(self.target_language),
            "detected_language": detected_language,
            "detected_language_display": language_display_name(detected_language)
            if detected_language in {"zh", "en"}
            else "Unknown",
            "switch_applied": switch_needed,
            "translated_issue_count": translated_issue_count,
            "translation_error_count": translation_error_count,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            **aggregate_metrics,
        }
        report_copy["report_language"] = self.target_language
        report_copy["language_switch"] = metadata
        return report_copy, metadata

    def detect_report_language(self, report_data: Dict[str, Any]) -> str:
        chunks: List[str] = []
        for issue in report_data.get("issues", []):
            if not isinstance(issue, dict):
                continue
            for field_name in TRANSLATABLE_FIELDS:
                value = str(issue.get(field_name, "") or "").strip()
                if value:
                    chunks.append(value)
        if not chunks:
            return "unknown"
        joined = "\n".join(chunks[:80])
        return detect_text_language(joined)

    def _build_issue_batches(self, issues: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        batches: List[List[Dict[str, Any]]] = []
        current_batch: List[Dict[str, Any]] = []
        current_chars = 0

        for index, issue in enumerate(issues, start=1):
            issue["_translation_id"] = index
            issue_payload = self._build_issue_payload(issue)
            payload_chars = len(json.dumps(issue_payload, ensure_ascii=False))
            if current_batch and current_chars + payload_chars > self.batch_chars:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(issue)
            current_chars += payload_chars

        if current_batch:
            batches.append(current_batch)
        return batches

    @staticmethod
    def _build_issue_payload(issue: Dict[str, Any]) -> Dict[str, Any]:
        translation_id = int(issue.get("_translation_id", issue.get("id", 0)) or 0)
        payload = {"id": translation_id}
        for field_name in TRANSLATABLE_FIELDS:
            payload[field_name] = str(issue.get(field_name, "") or "")
        return payload

    def _build_messages(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        language_name = language_display_name(self.target_language)
        items_payload = [self._build_issue_payload(issue) for issue in issues]
        system_prompt = render_prompt_section_template(
            "language_switch_prompt.md",
            "system",
            fallback=(
                "You are a precise translation editor for academic review reports. "
                "Translate the provided issue fields into {{language_name}}."
            ),
            language_name=language_name,
        )
        user_message = render_prompt_section_template(
            "language_switch_prompt.md",
            "user",
            fallback='{"target_language":"{{target_language}}","items":{{items_json}}}',
            target_language=self.target_language,
            items_json=json.dumps(items_payload, ensure_ascii=False, indent=2),
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    @staticmethod
    def _apply_issue_translation(issue: Dict[str, Any], translated_item: Dict[str, Any]) -> None:
        for field_name in TRANSLATABLE_FIELDS:
            translated_value = str(translated_item.get(field_name, "") or "").strip()
            original_value = str(issue.get(field_name, "") or "")
            if translated_value and translated_value != original_value:
                original_field_name = f"{field_name}{ORIGINAL_FIELD_SUFFIX}"
                issue.setdefault(original_field_name, original_value)
                issue[field_name] = translated_value
