from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings


@dataclass(slots=True)
class WebMCPClient:
    endpoint_url: str | None = None
    timeout: float = 30.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.endpoint_url is None and settings.WEB_MCP_URL is not None:
            self.endpoint_url = str(settings.WEB_MCP_URL)
        self.timeout = self.timeout or 30.0

    def is_available(self) -> bool:
        return self.enabled and bool(str(self.endpoint_url or "").strip())

    def search(self, query: str, *, top_k: int = 5) -> dict[str, Any]:
        return self._call_tool_sync(
            "web_search",
            {
                "query": str(query or "").strip(),
                "max_results": max(1, top_k),
            },
        )

    def fetch(self, url: str, *, max_chars: int = 20_000) -> dict[str, Any]:
        return self._call_tool_sync(
            "web_fetch",
            {
                "url": str(url or "").strip(),
                "max_chars": max(1000, min(int(max_chars), 100_000)),
            },
        )

    def read(
        self,
        url: str,
        *,
        selector: str = "body",
        wait_ms: int = 800,
        max_chars: int = 20_000,
    ) -> dict[str, Any]:
        return self._call_tool_sync(
            "browser_retrieve",
            {
                "url": str(url or "").strip(),
                "selector": selector,
                "wait_ms": max(0, int(wait_ms)),
                "max_chars": max(1000, min(int(max_chars), 100_000)),
            },
        )

    def verify(
        self,
        *,
        query: str,
        planned_queries: list[str] | None = None,
        top_k: int = 3,
        seed_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._call_tool_sync(
            "verify_web_evidence",
            {
                "query": str(query or "").strip(),
                "planned_queries": list(planned_queries or []),
                "top_k": max(1, int(top_k)),
                "seed_urls": list(seed_urls or []),
            },
        )

    def _call_tool_sync(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(self.endpoint_url or "").strip()
        if not self.enabled or not endpoint:
            return {}

        try:
            return asyncio.run(self._call_tool_async(endpoint, tool_name, arguments))
        except Exception:
            return {}

    async def _call_tool_async(
        self,
        endpoint: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception:
            return {}

        headers = self._build_headers(endpoint)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=headers,
        ) as http_client:
            async with streamable_http_client(endpoint, http_client=http_client) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return self._normalize_result(result, tool_name)

    def _normalize_result(self, result: Any, tool_name: str) -> dict[str, Any]:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured

        text = self._extract_text(getattr(result, "content", None))
        if not text:
            return {}

        payload = _parse_json_object(text)
        if isinstance(payload, dict):
            return payload

        return {"tool": tool_name, "text": text}

    def _extract_text(self, content: Any) -> str:
        if not content:
            return ""

        parts: list[str] = []
        items = content if isinstance(content, list) else [content]
        for item in items:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append(text)
                continue
            if isinstance(item, dict):
                for key in ("text", "content", "value", "message"):
                    value = item.get(key)
                    text = str(value or "").strip()
                    if text:
                        parts.append(text)
                        break
                continue
            for attr in ("text", "content", "value", "message"):
                value = getattr(item, attr, None)
                text = str(value or "").strip()
                if text:
                    parts.append(text)
                    break
            else:
                text = str(item).strip()
                if text:
                    parts.append(text)
        return _normalize_text("\n".join(parts))

    def _build_headers(self, endpoint: str) -> dict[str, str]:
        parsed = urlparse(endpoint)
        headers: dict[str, str] = {}
        if parsed.hostname in {"localhost", "127.0.0.1"} and parsed.port == 3001:
            headers["Host"] = "localhost:3000"
        return headers


def _normalize_text(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip()
    if not candidate.startswith("{") or not candidate.endswith("}"):
        return None
    try:
        payload = json.loads(candidate)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
