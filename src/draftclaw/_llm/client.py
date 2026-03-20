from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx

from draftclaw._core.config import LLMConfig
from draftclaw._core.exceptions import LLMRequestError


class OpenAICompatClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._session_depth = 0

    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.api_key.strip():
            raise LLMRequestError(
                "LLM API key is not configured. Set `DraftClawSettings.llm.api_key` or `OPENAI_API_KEY`."
            )

        client = self._client
        if client is None:
            async with self.session():
                return await self.create_chat_completion(payload)

        return await self._post_json(client, payload)

    @asynccontextmanager
    async def session(self):
        if self._client is None:
            self._client = self._build_client()
        self._session_depth += 1
        try:
            yield self._client
        finally:
            self._session_depth -= 1
            if self._session_depth == 0 and self._client is not None:
                client = self._client
                self._client = None
                await client.aclose()

    def _build_client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=min(15.0, self.config.timeout_sec),
            read=self.config.timeout_sec,
            write=min(30.0, self.config.timeout_sec),
            pool=min(15.0, self.config.timeout_sec),
        )
        limits = httpx.Limits(
            max_keepalive_connections=16,
            max_connections=32,
            keepalive_expiry=60.0,
        )
        return httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
        )

    def _request_parts(self) -> tuple[str, dict[str, str]]:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return url, headers

    async def _post_json(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
        url, headers = self._request_parts()
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000]
            raise LLMRequestError(f"LLM HTTP error {exc.response.status_code} at {url}: {body}") from exc
        except httpx.ReadTimeout as exc:
            raise LLMRequestError(f"LLM request timeout after {self.config.timeout_sec}s at {url}") from exc
        except httpx.HTTPError as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            raise LLMRequestError(f"LLM request failed ({exc.__class__.__name__}) at {url}: {detail}") from exc

        return response.json()
