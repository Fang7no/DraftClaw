"""
Shared utilities for chat-completion style LLM calls.
"""

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import json
from math import ceil
import mimetypes
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import unquote

import requests

from env_utils import load_runtime_dotenv


load_runtime_dotenv(override=True)


LLM_STREAMING_ENABLED = os.getenv("LLM_STREAMING_ENABLED", "false").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LLM_STREAM_CONNECT_TIMEOUT = int(os.getenv("LLM_STREAM_CONNECT_TIMEOUT", "20") or 20)
LLM_STREAM_READ_TIMEOUT = int(os.getenv("LLM_STREAM_READ_TIMEOUT", "600") or 600)
LLM_ENABLE_THINKING = os.getenv("LLM_ENABLE_THINKING")
_CANCEL_CONTEXT = threading.local()
_REQUEST_RATE_LOCK = threading.Lock()
_LAST_REQUEST_STARTED_AT = 0.0


class LLMRequestCancelled(RuntimeError):
    """Raised when a user-requested cancellation interrupts an LLM call."""


class LLMEmptyStreamingResponse(RuntimeError):
    """Raised when a streamed response finishes without assistant content."""


def _active_cancel_checker() -> Any:
    return getattr(_CANCEL_CONTEXT, "checker", None)


def is_llm_cancel_requested() -> bool:
    checker = _active_cancel_checker()
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def raise_if_llm_cancelled() -> None:
    if is_llm_cancel_requested():
        raise LLMRequestCancelled("LLM request cancelled")


def get_llm_request_min_interval_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("LLM_REQUEST_MIN_INTERVAL_SECONDS", "0") or 0))
    except ValueError:
        return 0.0


def wait_for_llm_request_slot() -> None:
    """Throttle start times for all LLM HTTP requests in this process."""
    global _LAST_REQUEST_STARTED_AT

    min_interval = get_llm_request_min_interval_seconds()
    if min_interval <= 0:
        return

    with _REQUEST_RATE_LOCK:
        while True:
            raise_if_llm_cancelled()
            now = time.monotonic()
            wait_seconds = (_LAST_REQUEST_STARTED_AT + min_interval) - now
            if wait_seconds <= 0:
                _LAST_REQUEST_STARTED_AT = now
                return
            time.sleep(min(wait_seconds, 0.25))


@contextmanager
def llm_cancel_context(cancel_checker: Any):
    previous_checker = _active_cancel_checker()
    _CANCEL_CONTEXT.checker = cancel_checker
    try:
        yield
    finally:
        if previous_checker is None:
            try:
                delattr(_CANCEL_CONTEXT, "checker")
            except AttributeError:
                pass
        else:
            _CANCEL_CONTEXT.checker = previous_checker


@dataclass
class LLMCallResult:
    """Structured result for one chat-completion call."""

    content: str
    elapsed_seconds: float
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usage_source: str
    request_chars: int
    response_chars: int
    raw_usage: Dict[str, Any]
    streaming: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "usage_source": self.usage_source,
            "request_chars": self.request_chars,
            "response_chars": self.response_chars,
            "raw_usage": self.raw_usage,
            "streaming": self.streaming,
        }


def normalize_chat_api_url(api_url: str) -> str:
    api_url = api_url.rstrip("/")
    if not api_url:
        return api_url
    if api_url.endswith("/chat/completions"):
        return api_url
    if api_url.endswith("/compatible-mode"):
        return f"{api_url}/v1/chat/completions"
    if api_url.endswith("/v1"):
        return f"{api_url}/chat/completions"
    if api_url == "https://api.openai.com":
        return "https://api.openai.com/v1/chat/completions"
    return api_url


def flatten_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(str(item.get("content", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def is_multimodal_model(model: str) -> bool:
    lowered = model.lower()
    return any(marker in lowered for marker in ("vl", "omni"))


def parse_env_bool(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


IMAGE_MARKDOWN_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def normalize_image_ref(value: str) -> str:
    text = unquote(str(value or "")).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lower()


@lru_cache(maxsize=256)
def file_to_data_url(file_path: str) -> str:
    resolved = str(Path(file_path).resolve())
    mime_type, _ = mimetypes.guess_type(resolved)
    if not mime_type:
        mime_type = "application/octet-stream"

    encoded = base64.b64encode(Path(resolved).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_multimodal_user_content(
    prompt_text: str,
    image_inputs: Iterable[Dict[str, Any]],
    *,
    min_pixels: int,
    max_pixels: int,
) -> Any:
    images = [image for image in image_inputs if image.get("local_path")]
    if not images:
        return prompt_text

    content: List[Dict[str, Any]] = []
    image_lookup: Dict[str, Dict[str, Any]] = {}
    for image in images:
        refs = [str(image.get("img_path", "") or "")]
        source_paths = image.get("source_image_paths", [])
        if isinstance(source_paths, list):
            refs.extend(str(path) for path in source_paths)
        for ref in refs:
            normalized = normalize_image_ref(ref)
            if normalized:
                image_lookup[normalized] = image

    inserted_image_ids: set[int] = set()

    def append_text(text: str) -> None:
        if text:
            content.append({"type": "text", "text": text})

    def append_image(image: Dict[str, Any]) -> None:
        inserted_image_ids.add(id(image))
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": file_to_data_url(str(image["local_path"]))},
                "min_pixels": min_pixels,
                "max_pixels": max_pixels,
            }
        )

    cursor = 0
    for match in IMAGE_MARKDOWN_PATTERN.finditer(prompt_text):
        append_text(prompt_text[cursor : match.start()])
        image_ref = normalize_image_ref(match.group(1))
        image = image_lookup.get(image_ref)
        if image:
            if id(image) not in inserted_image_ids:
                append_image(image)
        else:
            append_text(match.group(0))
        cursor = match.end()
    append_text(prompt_text[cursor:])

    missing_images = [image for image in images if id(image) not in inserted_image_ids]
    if missing_images:
        append_text(
            "\n\nThe following images are referenced by this chunk but were not present as inline Markdown image tags:\n"
        )
        for image in missing_images:
            append_image(image)

    return content


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0

    cjk_chars = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))
    other_chars = max(0, len(text) - cjk_chars)
    return max(1, cjk_chars + ceil(other_chars / 4))


def estimate_message_tokens(messages: Iterable[Dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += 6
        total += estimate_text_tokens(str(message.get("role", "")))
        total += estimate_text_tokens(flatten_message_content(message.get("content", "")))
        if "name" in message:
            total += estimate_text_tokens(str(message["name"]))
    return total + 4


def extract_json_payload(response_text: str) -> Any:
    response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
    if fenced_match:
        fenced_body = fenced_match.group(1).strip()
        try:
            return json.loads(fenced_body)
        except json.JSONDecodeError:
            pass

    for start_char, end_char in (("{", "}"), ("[", "]")):
        start_idx = response_text.find(start_char)
        if start_idx == -1:
            continue

        depth = 0
        in_string = False
        escape = False
        for idx in range(start_idx, len(response_text)):
            char = response_text[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == start_char:
                depth += 1
            elif char == end_char:
                depth -= 1
                if depth == 0:
                    candidate = response_text[start_idx : idx + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Unable to parse JSON payload from response: {response_text[:500]}")


class ChatCompletionClient:
    """Minimal retrying client for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        default_timeout: int = 120,
        max_retries: int = 3,
    ):
        self.api_url = normalize_chat_api_url(api_url)
        self.api_key = api_key
        self.model = model
        self.default_timeout = default_timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def complete(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1800,
        response_format: Dict[str, Any] | None = None,
        timeout: int | None = None,
        stream: bool | None = None,
    ) -> LLMCallResult:
        messages_list = list(messages)
        streaming_enabled = LLM_STREAMING_ENABLED if stream is None else bool(stream)
        base_payload = {
            "model": self.model,
            "messages": messages_list,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            base_payload["response_format"] = response_format
        enable_thinking = self._resolve_enable_thinking()
        if enable_thinking is not None:
            base_payload["enable_thinking"] = enable_thinking
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        timeout = timeout or self.default_timeout
        stream_timeout: int | tuple[int, int] = timeout
        if streaming_enabled:
            stream_timeout = (
                LLM_STREAM_CONNECT_TIMEOUT,
                max(int(timeout), LLM_STREAM_READ_TIMEOUT),
            )
        last_error: Exception | None = None
        request_chars = sum(
            len(str(message.get("role", ""))) + len(flatten_message_content(message.get("content", "")))
            for message in messages_list
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                raise_if_llm_cancelled()
                started_at = time.perf_counter()

                fallback_reason = ""
                if streaming_enabled:
                    stream_payload = dict(base_payload)
                    stream_payload["stream"] = True
                    try:
                        content, raw_usage, used_streaming = self._request_completion_content(
                            headers=headers,
                            payload=stream_payload,
                            timeout=stream_timeout,
                            stream=True,
                        )
                    except LLMEmptyStreamingResponse as exc:
                        fallback_reason = str(exc)
                        content, raw_usage, used_streaming = self._request_completion_content(
                            headers=headers,
                            payload=base_payload,
                            timeout=timeout,
                            stream=False,
                        )
                    except requests.RequestException as exc:
                        if not self._should_fallback_from_stream_error(exc):
                            raise
                        fallback_reason = self._describe_request_exception(exc)
                        content, raw_usage, used_streaming = self._request_completion_content(
                            headers=headers,
                            payload=base_payload,
                            timeout=timeout,
                            stream=False,
                        )
                else:
                    content, raw_usage, used_streaming = self._request_completion_content(
                        headers=headers,
                        payload=base_payload,
                        timeout=timeout,
                        stream=False,
                    )
                elapsed_seconds = time.perf_counter() - started_at

                if fallback_reason:
                    raw_usage = dict(raw_usage)
                    raw_usage["_stream_fallback"] = True
                    raw_usage["_stream_fallback_reason"] = fallback_reason[:1000]

                if not content.strip():
                    raise RuntimeError("LLM response contained no assistant content")

                return self._build_call_result(
                    content=content,
                    elapsed_seconds=elapsed_seconds,
                    request_chars=request_chars,
                    raw_usage=raw_usage,
                    streaming=used_streaming,
                    messages_list=messages_list,
                )
            except requests.RequestException as exc:
                last_error = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                should_retry = attempt < self.max_retries and (
                    status_code in {408, 409, 429, 500, 502, 503, 504} or status_code is None
                )
                if not should_retry:
                    raise
                time.sleep(min(2 ** (attempt - 1), 6))

        if last_error:
            raise last_error
        raise RuntimeError("LLM request failed without a captured exception")

    def _request_completion_content(
        self,
        *,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int | tuple[int, int],
        stream: bool,
    ) -> tuple[str, Dict[str, Any], bool]:
        raise_if_llm_cancelled()
        wait_for_llm_request_slot()
        response = self.session.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=timeout,
            stream=stream,
        )
        self._raise_for_status_with_body(response)

        if stream:
            content, raw_usage, stream_debug = self._read_streaming_response(response)
            if not content.strip():
                raise LLMEmptyStreamingResponse(self._format_empty_stream_message(stream_debug))
            return content, raw_usage, True

        content, raw_usage = self._read_non_streaming_response(response)
        return content, raw_usage, False

    @staticmethod
    def _read_non_streaming_response(response: requests.Response) -> tuple[str, Dict[str, Any]]:
        body = response.json()
        if not isinstance(body, dict):
            return flatten_message_content(body), {}

        content = ChatCompletionClient._extract_content_from_non_stream_payload(body)
        raw_usage = body.get("usage", {})
        if not isinstance(raw_usage, dict):
            raw_usage = {}

        output = body.get("output")
        if not raw_usage and isinstance(output, dict) and isinstance(output.get("usage"), dict):
            raw_usage = output["usage"]
        return content, raw_usage

    @staticmethod
    def _read_streaming_response(response: requests.Response) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
        content_parts: List[str] = []
        raw_usage: Dict[str, Any] = {}
        last_payload: Dict[str, Any] = {}
        payload_previews: List[str] = []
        parsed_events = 0
        ignored_lines = 0

        for raw_line in response.iter_lines(decode_unicode=True):
            raise_if_llm_cancelled()
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                if line == "[DONE]":
                    break
                continue

            if len(payload_previews) < 8:
                payload_previews.append(line[:500])

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                ignored_lines += 1
                continue
            if not isinstance(payload, dict):
                ignored_lines += 1
                continue

            parsed_events += 1
            last_payload = payload
            usage = payload.get("usage")
            if isinstance(usage, dict):
                raw_usage = usage

            content_parts.extend(ChatCompletionClient._extract_content_from_choices(payload.get("choices", [])))

            output = payload.get("output")
            if isinstance(output, dict):
                output_usage = output.get("usage")
                if isinstance(output_usage, dict):
                    raw_usage = output_usage
                if output.get("text") is not None:
                    content_parts.append(str(output.get("text")))
                elif output.get("content") is not None:
                    content_parts.append(flatten_message_content(output.get("content")))
                content_parts.extend(ChatCompletionClient._extract_content_from_choices(output.get("choices", [])))

        content = "".join(content_parts)
        if not content and last_payload:
            content = ChatCompletionClient._extract_content_from_non_stream_payload(last_payload)
        return content, raw_usage, {
            "parsed_events": parsed_events,
            "ignored_lines": ignored_lines,
            "payload_previews": payload_previews,
            "last_payload_preview": json.dumps(last_payload, ensure_ascii=False)[:1000] if last_payload else "",
        }

    @staticmethod
    def _extract_content_from_choices(choices: Any) -> List[str]:
        if not isinstance(choices, list):
            return []

        parts: List[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            for message_key in ("delta", "message"):
                message = choice.get(message_key)
                if not isinstance(message, dict):
                    continue
                if message.get("content") is not None:
                    parts.append(flatten_message_content(message.get("content")))
                elif message.get("text") is not None:
                    parts.append(str(message.get("text")))

            if choice.get("content") is not None:
                parts.append(flatten_message_content(choice.get("content")))
            elif choice.get("text") is not None:
                parts.append(str(choice.get("text")))

        return parts

    @staticmethod
    def _extract_content_from_non_stream_payload(payload: Dict[str, Any]) -> str:
        try:
            parts = ChatCompletionClient._extract_content_from_choices(payload.get("choices", []))
            if parts:
                return "".join(parts)

            output = payload.get("output")
            if isinstance(output, dict):
                if output.get("text") is not None:
                    return str(output.get("text"))
                if output.get("content") is not None:
                    return flatten_message_content(output.get("content"))
                output_parts = ChatCompletionClient._extract_content_from_choices(output.get("choices", []))
                if output_parts:
                    return "".join(output_parts)
        except Exception:
            return ""
        return ""

    @staticmethod
    def _format_empty_stream_message(stream_debug: Dict[str, Any]) -> str:
        previews = stream_debug.get("payload_previews", [])
        preview_text = " | ".join(str(item) for item in previews)[:1000] if previews else "no data payloads"
        return (
            "Streaming response contained no assistant content "
            f"(events={stream_debug.get('parsed_events', 0)}, "
            f"ignored_lines={stream_debug.get('ignored_lines', 0)}, preview={preview_text})"
        )

    @staticmethod
    def _should_fallback_from_stream_error(exc: requests.RequestException) -> bool:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return status_code is None or status_code in {400, 408, 409, 422, 500, 502, 503, 504}

    @staticmethod
    def _raise_for_status_with_body(response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            response_text = ""
            try:
                response_text = str(response.text)[:1000]
            except Exception:
                response_text = ""
            if response_text:
                raise requests.HTTPError(
                    f"{exc}; response body: {response_text}",
                    response=getattr(exc, "response", response),
                    request=getattr(exc, "request", None),
                ) from exc
            raise

    @staticmethod
    def _describe_request_exception(exc: requests.RequestException) -> str:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        response_text = ""
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                response_text = str(response.text)[:1000]
            except Exception:
                response_text = ""
        if status_code is not None:
            suffix = f"; body={response_text}" if response_text else ""
            return f"Streaming request failed with HTTP {status_code}: {exc}{suffix}"
        return f"Streaming request failed with {exc.__class__.__name__}: {exc}"

    def _resolve_enable_thinking(self) -> bool | None:
        if LLM_ENABLE_THINKING is not None:
            return parse_env_bool(LLM_ENABLE_THINKING)

        # DashScope Qwen3 rejects non-streaming calls unless thinking is disabled.
        # These agents require concise JSON, so disabling thinking is also the safer
        # default for streamed structured-output calls.
        if "qwen3" in self.model.lower():
            return False
        return None

    def _build_call_result(
        self,
        *,
        content: str,
        elapsed_seconds: float,
        request_chars: int,
        raw_usage: Dict[str, Any],
        streaming: bool,
        messages_list: List[Dict[str, Any]],
    ) -> LLMCallResult:
        estimated_prompt_tokens = estimate_message_tokens(messages_list)
        estimated_completion_tokens = estimate_text_tokens(content)

        prompt_tokens = raw_usage.get("prompt_tokens")
        completion_tokens = raw_usage.get("completion_tokens")
        total_tokens = raw_usage.get("total_tokens")

        usage_source = "api"
        if not isinstance(prompt_tokens, int):
            prompt_tokens = estimated_prompt_tokens
            usage_source = "estimated"
        if not isinstance(completion_tokens, int):
            completion_tokens = estimated_completion_tokens
            usage_source = "estimated"
        if not isinstance(total_tokens, int):
            total_tokens = prompt_tokens + completion_tokens
            usage_source = "estimated"

        return LLMCallResult(
            content=content,
            elapsed_seconds=elapsed_seconds,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            usage_source=usage_source,
            request_chars=request_chars,
            response_chars=len(content),
            raw_usage=raw_usage,
            streaming=streaming,
        )
