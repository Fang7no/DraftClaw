"""
Search agent for web-based claim verification.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import requests

from agents.llm_utils import ChatCompletionClient, LLMCallResult, extract_json_payload
import config
from logger import AgentLogger
from prompt_loader import load_prompt_section_text, render_prompt_section_template


DEFAULT_SEARCH_INTENT_SYSTEM_PROMPT = """You are DraftClaw's Search Agent.

Identify the search intent for an issue, then generate precise search keywords and queries.
Do not make the final judgment. Return JSON only."""

DEFAULT_SEARCH_ORGANIZE_SYSTEM_PROMPT = """You are DraftClaw's Search Agent.

Organize explicit search requests and raw search hits into compact search_results.
Do not make the final judgment. Return JSON only."""


DEFAULT_SEARCH_INTENT_USER_PROMPT = """Generate search intent and queries for this issue.

Issue type: {{issue_type}}
Description: {{description}}
Evidence: {{evidence}}

Return JSON only with search_intent, search_keywords, search_queries."""

DEFAULT_SEARCH_ORGANIZE_USER_PROMPT = """Organize the raw search hits for these search requests.

Current chunk:
{{current_chunk}}

search_requests:
{{search_requests_markdown}}

raw_search_results:
{{raw_search_results_markdown}}

Return JSON only with search_results."""

SEARCH_INTENT_PROMPT_FILE = "search/intent_prompt.md"
SEARCH_ORGANIZE_PROMPT_FILE = "search/organize_results_prompt.md"


MOCK_MODE = False


class SearchAgent:
    """Perform web searches to verify specific issue types during exploration."""

    def __init__(self, logger: Optional[AgentLogger] = None, enabled: Optional[bool] = None):
        self.logger = logger
        self._enabled_override = enabled
        self.intent_system_prompt = load_prompt_section_text(
            SEARCH_INTENT_PROMPT_FILE,
            "system",
            fallback=DEFAULT_SEARCH_INTENT_SYSTEM_PROMPT,
        )
        self.organize_system_prompt = load_prompt_section_text(
            SEARCH_ORGANIZE_PROMPT_FILE,
            "system",
            fallback=DEFAULT_SEARCH_ORGANIZE_SYSTEM_PROMPT,
        )
        self.model_name = config.SEARCH_MODEL
        self.client = ChatCompletionClient(
            api_url=config.SEARCH_API_URL,
            api_key=config.SEARCH_API_KEY,
            model=self.model_name,
            default_timeout=60,
            max_retries=2,
        )

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        return False

    def parse_search_intent(
        self,
        *,
        issue_type: str,
        description: str,
        evidence: str,
        chunk_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        user_prompt = render_prompt_section_template(
            SEARCH_INTENT_PROMPT_FILE,
            "user",
            fallback=DEFAULT_SEARCH_INTENT_USER_PROMPT,
            issue_type=issue_type,
            description=description,
            evidence=evidence,
        )
        messages = [
            {"role": "system", "content": self.intent_system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "intent_input",
                chunk_id=chunk_id,
                input_data={
                    "issue_type": issue_type,
                    "description": description,
                    "evidence": evidence,
                },
                message="Parsing search intent",
            )
            self.logger.log(
                "SearchAgent",
                "intent_llm_input",
                chunk_id=chunk_id,
                data={"model": self.model_name},
                input_data={"llm_messages": messages},
                message="Calling search intent model",
            )

        llm_result = self._call_llm_intent(user_prompt)
        if self.logger:
            self.logger.log(
                "SearchAgent",
                "intent_llm_output",
                chunk_id=chunk_id,
                data={"llm_metrics": llm_result.to_dict()},
                output_data={"llm_output": llm_result.content},
                message="Search intent model raw output",
            )
        parsed = self._normalize_intent_result(llm_result.content)
        parsed["_llm_metrics"] = llm_result.to_dict()

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "intent_output",
                chunk_id=chunk_id,
                data={"llm_metrics": llm_result.to_dict()},
                output_data=parsed,
                message="Search intent parsed",
            )

        return parsed

    def run_requests(
        self,
        *,
        current_chunk: str,
        search_requests: List[Dict[str, Any]],
        chunk_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized_requests = self._normalize_search_requests(search_requests)

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "batch_input",
                chunk_id=chunk_id,
                input_data={
                    "current_chunk": current_chunk,
                    "search_requests": normalized_requests,
                },
                message=f"Running {len(normalized_requests)} search requests",
            )

        if not self.enabled:
            return {
                "search_results": [],
                "raw_search_results": [],
                "_llm_metrics": {},
                "search_performed": False,
            }

        if not normalized_requests:
            return {
                "search_results": [],
                "raw_search_results": [],
                "_llm_metrics": {},
                "search_performed": False,
            }

        raw_search_results: List[Dict[str, Any]] = []
        for request in normalized_requests:
            performed = self.perform_search(
                search_keywords=[request["query"]],
                search_queries=[request["query"]],
                max_results=config.SEARCH_MAX_RESULTS,
                chunk_id=chunk_id,
            )
            raw_search_results.append(
                {
                    "request_id": request["request_id"],
                    "goal": request["goal"],
                    "query": request["query"],
                    "results": performed.get("results", []),
                    "search_engine": performed.get("search_engine", "unknown"),
                }
            )

        search_results, llm_metrics = self._organize_search_results(
            current_chunk=current_chunk,
            search_requests=normalized_requests,
            raw_search_results=raw_search_results,
            chunk_id=chunk_id,
        )
        result = {
            "search_results": search_results,
            "raw_search_results": raw_search_results,
            "_llm_metrics": llm_metrics,
            "search_performed": True,
        }

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "batch_output",
                chunk_id=chunk_id,
                data={"llm_metrics": llm_metrics},
                output_data=result,
                message=f"Organized {len(search_results)} search results",
            )

        return result

    def perform_search(
        self,
        *,
        search_keywords: List[str],
        search_queries: List[str],
        max_results: int = 5,
        chunk_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if str(config.SEARCH_ENGINE or "").strip().lower() == "serper" and str(config.SERPER_API_KEY or "").strip():
            return self._serper_search(search_queries, max_results, chunk_id)
        return self._duckduckgo_search(search_keywords, search_queries, max_results, chunk_id)

    def _duckduckgo_search(
        self,
        keywords: List[str],
        queries: List[str],
        max_results: int,
        chunk_id: Optional[int],
    ) -> Dict[str, Any]:
        results: List[Dict[str, str]] = []
        seen_urls = set()

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "search_request",
                chunk_id=chunk_id,
                data={"engine": "duckduckgo", "keywords": keywords, "queries": queries},
                message="Starting DuckDuckGo search",
            )

        try:
            for query in queries[:3]:
                query = query.strip()
                if not query:
                    continue

                url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
                response = requests.get(
                    url,
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; DraftClaw/1.0)"},
                )
                if response.status_code != 200:
                    continue

                for line in response.text.split("\n"):
                    if 'class="result__a"' not in line:
                        continue
                    link_match = re.search(r'href="(https?://[^"]+)"', line)
                    title_match = re.search(r'class="result__a"[^>]*>([^<]+)</a>', line)
                    if not link_match or not title_match:
                        continue
                    url_found = link_match.group(1)
                    if url_found in seen_urls or len(results) >= max_results:
                        continue
                    seen_urls.add(url_found)
                    results.append(
                        {
                            "title": title_match.group(1).strip(),
                            "url": url_found,
                            "snippet": "",
                        }
                    )
                if len(results) >= max_results:
                    break
        except Exception as exc:
            if self.logger:
                self.logger.log(
                    "SearchAgent",
                    "search_error",
                    chunk_id=chunk_id,
                    data={"engine": "duckduckgo", "error": str(exc)},
                    message=f"Search failed: {exc}",
                )
            results = []

        payload = {
            "results": results,
            "search_engine": "duckduckgo",
            "results_count": len(results),
        }

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "search_output",
                chunk_id=chunk_id,
                output_data=payload,
                message=f"DuckDuckGo returned {len(results)} results",
            )

        return payload

    def _serper_search(
        self,
        queries: List[str],
        max_results: int,
        chunk_id: Optional[int],
    ) -> Dict[str, Any]:
        results: List[Dict[str, str]] = []

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "search_request",
                chunk_id=chunk_id,
                data={"engine": "serper", "queries": queries},
                message="Starting Serper search",
            )

        try:
            headers = {
                "X-API-KEY": config.SERPER_API_KEY,
                "Content-Type": "application/json",
            }
            for query in queries[:3]:
                payload = {"q": query, "num": max_results}
                resp = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json=payload,
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("organic", [])[:max_results]:
                    results.append(
                        {
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "snippet": item.get("snippet", ""),
                        }
                    )
                if len(results) >= max_results:
                    break
        except Exception as exc:
            if self.logger:
                self.logger.log(
                    "SearchAgent",
                    "search_error",
                    chunk_id=chunk_id,
                    data={"engine": "serper", "error": str(exc)},
                    message=f"Search failed: {exc}",
                )
            results = []

        payload = {
            "results": results,
            "search_engine": "serper",
            "results_count": len(results),
        }

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "search_output",
                chunk_id=chunk_id,
                output_data=payload,
                message=f"Serper returned {len(results)} results",
            )

        return payload

    def search(
        self,
        *,
        finding: Dict[str, Any],
        chunk_context: str,
        chunk_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if self.logger:
            self.logger.log(
                "SearchAgent",
                "input",
                chunk_id=chunk_id,
                input_data={
                    "finding_type": finding.get("type"),
                    "description": finding.get("description"),
                },
                message="Starting search for finding",
            )

        if not self.enabled:
            return {
                "search_performed": False,
                "reason": "SearchAgent is disabled",
                "search_intent": "",
                "search_keywords": [],
                "search_queries": [],
                "search_results": [],
            }

        issue_type = finding.get("type", "")
        description = finding.get("description", "")
        evidence = finding.get("chunk_evidence", "") or finding.get("evidence", "")

        intent_result = self.parse_search_intent(
            issue_type=issue_type,
            description=description,
            evidence=evidence,
            chunk_id=chunk_id,
        )

        search_keywords = intent_result.get("search_keywords", [])
        search_queries = intent_result.get("search_queries", [])
        if not search_keywords and not search_queries:
            return {
                "search_performed": False,
                "search_intent": intent_result.get("search_intent", ""),
                "search_keywords": [],
                "search_queries": [],
                "search_results": [],
            }

        search_results = self.perform_search(
            search_keywords=search_keywords,
            search_queries=search_queries,
            max_results=config.SEARCH_MAX_RESULTS,
            chunk_id=chunk_id,
        )

        result = {
            "search_performed": True,
            "search_intent": intent_result.get("search_intent", ""),
            "search_keywords": search_keywords,
            "search_queries": search_queries,
            "search_results": search_results.get("results", []),
            "search_engine": search_results.get("search_engine", "unknown"),
            "_llm_metrics": intent_result.get("_llm_metrics", {}),
        }

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "output",
                chunk_id=chunk_id,
                output_data=result,
                message=f"Search completed: {len(result['search_results'])} results",
            )

        return result

    def _call_llm_intent(self, prompt: str) -> LLMCallResult:
        if MOCK_MODE:
            content = json.dumps(
                {
                    "search_intent": "Find primary sources that can verify the disputed claim.",
                    "search_keywords": ["keyword1", "keyword2", "keyword3"],
                    "search_queries": ["query one", "query two"],
                },
                ensure_ascii=False,
            )
            return LLMCallResult(
                content=content,
                elapsed_seconds=0.0,
                model="mock-search-agent",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                usage_source="estimated",
                request_chars=len(prompt),
                response_chars=len(content),
                raw_usage={},
            )

        return self.client.complete(
            [
                {"role": "system", "content": self.intent_system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

    def _call_llm_organize(self, prompt: str) -> LLMCallResult:
        if MOCK_MODE:
            content = json.dumps({"search_results": []}, ensure_ascii=False)
            return LLMCallResult(
                content=content,
                elapsed_seconds=0.0,
                model="mock-search-agent",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                usage_source="estimated",
                request_chars=len(prompt),
                response_chars=len(content),
                raw_usage={},
            )

        return self.client.complete(
            [
                {"role": "system", "content": self.organize_system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )

    @staticmethod
    def _normalize_intent_result(payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, str):
            try:
                payload = json.dumps(payload)
            except (TypeError, ValueError):
                return {
                    "search_intent": "",
                    "search_keywords": [],
                    "search_queries": [],
                }

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {
                "search_intent": "",
                "search_keywords": [],
                "search_queries": [],
            }

        return {
            "search_intent": str(parsed.get("search_intent", "")),
            "search_keywords": SearchAgent._normalize_list(parsed.get("search_keywords")),
            "search_queries": SearchAgent._normalize_list(parsed.get("search_queries")),
        }

    def _organize_search_results(
        self,
        *,
        current_chunk: str,
        search_requests: List[Dict[str, str]],
        raw_search_results: List[Dict[str, Any]],
        chunk_id: Optional[int],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        user_prompt = render_prompt_section_template(
            SEARCH_ORGANIZE_PROMPT_FILE,
            "user",
            fallback=DEFAULT_SEARCH_ORGANIZE_USER_PROMPT,
            current_chunk=current_chunk,
            search_requests_markdown=self._search_requests_to_markdown(search_requests),
            raw_search_results_markdown=self._raw_results_to_markdown(raw_search_results),
        )
        messages = [
            {"role": "system", "content": self.organize_system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if self.logger:
            self.logger.log(
                "SearchAgent",
                "organize_llm_input",
                chunk_id=chunk_id,
                data={"model": self.model_name, "request_count": len(search_requests)},
                input_data={"llm_messages": messages},
                message="Calling search organization model",
            )
        llm_result = self._call_llm_organize(user_prompt)
        if self.logger:
            self.logger.log(
                "SearchAgent",
                "organize_llm_output",
                chunk_id=chunk_id,
                data={"llm_metrics": llm_result.to_dict()},
                output_data={"llm_output": llm_result.content},
                message="Search organization model raw output",
            )
        payload = extract_json_payload(llm_result.content)
        normalized = self._normalize_organized_results(payload, raw_search_results)

        if self.logger:
            self.logger.log(
                "SearchAgent",
                "organize_output",
                chunk_id=chunk_id,
                data={"llm_metrics": llm_result.to_dict()},
                output_data={"search_results": normalized},
                message=f"Organized {len(normalized)} search request results",
            )

        return normalized, llm_result.to_dict()

    @staticmethod
    def _normalize_search_requests(value: Any) -> List[Dict[str, str]]:
        items = value if isinstance(value, list) else [value]
        normalized: List[Dict[str, str]] = []
        seen = set()

        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            request_id = str(item.get("request_id", "") or "").strip() or f"request-{index}"
            goal = str(item.get("goal", "") or "").strip() or request_id
            query = str(item.get("query", "") or "").strip()
            if not query:
                continue
            fingerprint = (goal.lower(), query.lower())
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            normalized.append({"request_id": request_id, "goal": goal, "query": query})

        return normalized[:8]

    @staticmethod
    def _search_requests_to_markdown(search_requests: List[Dict[str, str]]) -> str:
        lines: List[str] = []
        for request in search_requests:
            lines.extend(
                [
                    f"- request_id: {request.get('request_id', '')}",
                    f"  goal: {request.get('goal', '')}",
                    f"  query: {request.get('query', '')}",
                ]
            )
        return "\n".join(lines).strip() or "- none"

    @staticmethod
    def _raw_results_to_markdown(raw_search_results: List[Dict[str, Any]]) -> str:
        blocks: List[str] = []
        for item in raw_search_results:
            header = [
                f"## {item.get('request_id', '')}",
                f"- goal: {item.get('goal', '')}",
                f"- query: {item.get('query', '')}",
                f"- engine: {item.get('search_engine', '')}",
            ]
            result_lines: List[str] = []
            for index, result in enumerate(item.get("results", []), start=1):
                result_lines.extend(
                    [
                        f"{index}. title: {result.get('title', '')}",
                        f"   url: {result.get('url', '')}",
                        f"   snippet: {result.get('snippet', '')}",
                    ]
                )
            if not result_lines:
                result_lines.append("1. no results")
            blocks.append("\n".join(header + result_lines))
        return "\n\n".join(blocks).strip() or "No raw search results."

    @staticmethod
    def _normalize_organized_results(
        payload: Any,
        raw_search_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return SearchAgent._fallback_organized_results(raw_search_results)

        items = payload.get("search_results", [])
        if not isinstance(items, list):
            return SearchAgent._fallback_organized_results(raw_search_results)

        raw_map = {
            str(item.get("request_id", "")).strip(): item
            for item in raw_search_results
            if isinstance(item, dict)
        }
        normalized: List[Dict[str, Any]] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            request_id = str(item.get("request_id", "") or "").strip()
            raw_item = raw_map.get(request_id, {})
            query = str(item.get("query", "") or raw_item.get("query", "")).strip()
            summary = str(item.get("summary", "") or "").strip()
            sources = item.get("sources", [])
            if not isinstance(sources, list):
                sources = []
            normalized_sources: List[Dict[str, str]] = []
            seen_urls = set()
            for source in sources:
                if not isinstance(source, dict):
                    continue
                title = str(source.get("title", "") or "").strip()
                url = str(source.get("url", "") or "").strip()
                snippet = str(source.get("snippet", "") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                normalized_sources.append(
                    {
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                    }
                )

            if not request_id:
                continue
            if not normalized_sources:
                normalized_sources = SearchAgent._fallback_sources(raw_item)
            normalized.append(
                {
                    "request_id": request_id,
                    "query": query,
                    "summary": summary,
                    "sources": normalized_sources[:5],
                }
            )

        return normalized or SearchAgent._fallback_organized_results(raw_search_results)

    @staticmethod
    def _fallback_sources(raw_item: Dict[str, Any]) -> List[Dict[str, str]]:
        sources: List[Dict[str, str]] = []
        seen_urls = set()
        for result in raw_item.get("results", [])[:5]:
            url = str(result.get("url", "") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(
                {
                    "title": str(result.get("title", "") or "").strip(),
                    "url": url,
                    "snippet": str(result.get("snippet", "") or "").strip(),
                }
            )
        return sources

    @staticmethod
    def _fallback_organized_results(raw_search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fallback: List[Dict[str, Any]] = []
        for item in raw_search_results:
            if not isinstance(item, dict):
                continue
            fallback.append(
                {
                    "request_id": str(item.get("request_id", "") or "").strip(),
                    "query": str(item.get("query", "") or "").strip(),
                    "summary": "",
                    "sources": SearchAgent._fallback_sources(item),
                }
            )
        return [item for item in fallback if item.get("request_id")]

    @staticmethod
    def _normalize_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return []
