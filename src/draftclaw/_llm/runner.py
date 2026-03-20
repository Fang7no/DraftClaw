from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from json import JSONDecodeError
from typing import Any

from pydantic import BaseModel, ValidationError

from draftclaw._core.config import LLMConfig
from draftclaw._core.exceptions import LLMOutputValidationError, LLMRequestError
from draftclaw._llm.cache import LLMCache
from draftclaw._llm.client import OpenAICompatClient


class LLMRunner:
    def __init__(self, config: LLMConfig, cache: LLMCache | None = None) -> None:
        self.config = config
        self.client = OpenAICompatClient(config)
        self.cache = cache

    @asynccontextmanager
    async def session(self):
        async with self.client.session():
            yield self

    async def run_contract(
        self,
        *,
        messages: list[dict[str, str]],
        schema_model: type[BaseModel],
        use_repair: bool = True,
    ) -> tuple[BaseModel, str, dict[str, Any], bool]:
        payload = self._build_payload(messages, schema_model)
        cache_key = LLMCache.make_key(payload)

        if self.cache and self.config.enable_cache:
            cached = self.cache.get(cache_key)
            if cached:
                validated = schema_model.model_validate(cached["parsed"])
                return validated, cached["raw_content"], cached.get("response", {}), True

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            raw_content = ""
            try:
                response = await self._call_with_fallback(payload)
                raw_content = self._extract_content(response)
                parsed = self._parse_json(raw_content)
                validated = schema_model.model_validate(parsed)
                if self.cache and self.config.enable_cache:
                    self.cache.set(
                        cache_key,
                        {
                            "parsed": validated.model_dump(mode="json"),
                            "raw_content": raw_content,
                            "response": response,
                        },
                    )
                return validated, raw_content, response, False
            except (JSONDecodeError, ValidationError) as exc:
                last_error = exc
                if use_repair:
                    repaired = await self._repair_output(messages, schema_model, raw_content, str(exc))
                    try:
                        parsed = self._parse_json(repaired)
                        validated = schema_model.model_validate(parsed)
                        if self.cache and self.config.enable_cache:
                            self.cache.set(
                                cache_key,
                                {
                                    "parsed": validated.model_dump(mode="json"),
                                    "raw_content": repaired,
                                    "response": {"repair": True},
                                },
                            )
                        return validated, repaired, {"repair": True}, False
                    except (JSONDecodeError, ValidationError) as repair_exc:
                        last_error = repair_exc
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_backoff_sec * attempt)
            except LLMRequestError as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_backoff_sec * attempt)

        if isinstance(last_error, LLMRequestError):
            raise last_error
        raise LLMOutputValidationError(f"Failed to produce valid structured output: {last_error}")

    def _build_payload(self, messages: list[dict[str, str]], schema_model: type[BaseModel]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.use_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_model.__name__,
                    "strict": True,
                    "schema": schema_model.model_json_schema(),
                },
            }
        return payload

    async def _call_with_fallback(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.client.create_chat_completion(payload)
        except LLMRequestError as exc:
            if "response_format" in payload and "response_format" in str(exc):
                fallback = dict(payload)
                fallback.pop("response_format", None)
                return await self.client.create_chat_completion(fallback)
            raise

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            raise JSONDecodeError("Missing choices", "", 0)
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            merged: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    merged.append(part.get("text", ""))
                else:
                    merged.append(str(part))
            return "".join(merged)
        return str(content)

    @staticmethod
    def _parse_json(raw_content: str) -> dict[str, Any]:
        text = raw_content.strip()
        if not text:
            raise JSONDecodeError("Empty content", text, 0)
        try:
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                raise JSONDecodeError("Top-level JSON must be object", text, 0)
            return loaded
        except JSONDecodeError:
            extracted = LLMRunner._extract_first_json_object(text)
            loaded = json.loads(extracted)
            if not isinstance(loaded, dict):
                raise JSONDecodeError("Top-level JSON must be object", text, 0)
            return loaded

    @staticmethod
    def _extract_first_json_object(text: str) -> str:
        start = text.find("{")
        if start == -1:
            raise JSONDecodeError("No JSON object found", text, 0)
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        raise JSONDecodeError("JSON object not closed", text, start)

    async def _repair_output(
        self,
        messages: list[dict[str, str]],
        schema_model: type[BaseModel],
        broken_output: str,
        error_message: str,
    ) -> str:
        repair_prompt = (
            "You must output one valid JSON object and nothing else.\n"
            "Repair the broken output so that it matches the schema below.\n"
            f"Schema: {json.dumps(schema_model.model_json_schema(), ensure_ascii=False)}\n"
            f"ValidationError: {error_message}\n"
            f"BrokenOutput: {broken_output}"
        )
        repair_messages = messages + [{"role": "user", "content": repair_prompt}]
        payload = {
            "model": self.config.model,
            "messages": repair_messages,
            "temperature": 0,
            "top_p": 1,
            "max_tokens": self.config.max_tokens,
        }
        response = await self.client.create_chat_completion(payload)
        return self._extract_content(response)
