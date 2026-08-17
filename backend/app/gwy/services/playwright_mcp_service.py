from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.gwy.services.web_mcp_client import WebMCPClient


@dataclass(slots=True)
class PlaywrightMCPService:
    endpoint_url: str | None = None
    enabled: bool = True
    web_mcp_enabled: bool = True
    timeout: float = 15.0
    http_client: Any | None = None

    def __post_init__(self) -> None:
        if self.endpoint_url is None and settings.PLAYWRIGHT_MCP_URL is not None:
            self.endpoint_url = str(settings.PLAYWRIGHT_MCP_URL)
        self.timeout = self.timeout or 15.0

    def read(
        self,
        url: str,
        *,
        selector: str = "body",
        wait_ms: int = 800,
        max_chars: int = 20_000,
    ) -> dict[str, Any]:
        normalized_url = str(url or "").strip()
        if not self.enabled or not normalized_url:
            return {}

        if self.web_mcp_enabled and settings.WEB_MCP_URL is not None:
            mcp_result = WebMCPClient(endpoint_url=str(settings.WEB_MCP_URL)).read(
                normalized_url,
                selector=selector,
                wait_ms=wait_ms,
                max_chars=max_chars,
            )
            if mcp_result:
                return self._normalize_result(
                    url=normalized_url,
                    final_url=_first_text(
                        mcp_result.get("final_url"),
                        mcp_result.get("url"),
                    )
                    or normalized_url,
                    title=_first_text(mcp_result.get("title")),
                    text=_first_text(mcp_result.get("text"), mcp_result.get("content"))
                    or "",
                    content_type=_first_text(mcp_result.get("content_type")),
                    status_code=mcp_result.get("status_code"),
                    source="playwright",
                    retrieved_via=str(
                        mcp_result.get("retrieved_via") or "web_mcp:browser_retrieve"
                    ),
                )

        mcp_result = self._read_via_mcp(normalized_url)
        if mcp_result:
            return mcp_result

        try:
            return self._read_via_local_playwright(
                normalized_url,
                selector=selector,
                wait_ms=wait_ms,
                max_chars=max_chars,
            )
        except TypeError:
            return self._read_via_local_playwright(normalized_url)

    def _read_via_mcp(self, url: str) -> dict[str, Any]:
        endpoint = str(self.endpoint_url or "").strip()
        if not endpoint:
            return {}

        try:
            return asyncio.run(self._read_via_mcp_async(url, endpoint))
        except Exception:
            return {}

    async def _read_via_mcp_async(self, url: str, endpoint: str) -> dict[str, Any]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception:
            return {}

        headers = self._build_mcp_headers(endpoint)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=headers,
        ) as http_client:
            async with streamable_http_client(endpoint, http_client=http_client) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    tool_name = self._select_mcp_tool_name(tools.tools)
                    if not tool_name:
                        return {}

                    arguments = self._build_mcp_arguments(tools.tools, tool_name, url)
                    result = await session.call_tool(tool_name, arguments)
                    return self._normalize_mcp_result(result, url, tool_name)

    def _select_mcp_tool_name(self, tools: list[Any]) -> str | None:
        candidates = ("url", "target", "page_url", "href", "input")
        ranked: list[tuple[int, str]] = []
        for tool in tools:
            name = str(getattr(tool, "name", "") or "").strip()
            if not name:
                continue
            schema = dict(getattr(tool, "inputSchema", {}) or {})
            properties = dict(schema.get("properties") or {})
            required = set(schema.get("required") or [])
            matching_fields = [field for field in candidates if field in properties]
            if not matching_fields:
                continue
            description = str(getattr(tool, "description", "") or "").lower()
            score = 0
            if any(field in required for field in matching_fields):
                score += 4
            if any(
                keyword in description
                for keyword in ("read", "page", "browser", "navigate", "open", "snapshot")
            ):
                score += 2
            if any(
                keyword in name.lower()
                for keyword in ("read", "page", "browser", "navigate", "open", "snapshot")
            ):
                score += 1
            ranked.append((score, name))
        if not ranked:
            return None
        return max(ranked, key=lambda item: item[0])[1]

    def _build_mcp_arguments(
        self,
        tools: list[Any],
        tool_name: str,
        url: str,
    ) -> dict[str, Any]:
        tool = next(
            (item for item in tools if str(getattr(item, "name", "") or "") == tool_name),
            None,
        )
        schema = dict(getattr(tool, "inputSchema", {}) or {})
        properties = dict(schema.get("properties") or {})
        candidates = ("url", "target", "page_url", "href", "input")
        for key in candidates:
            if key in properties:
                return {key: url}
        return {}

    def _normalize_mcp_result(
        self,
        result: Any,
        url: str,
        tool_name: str,
    ) -> dict[str, Any]:
        raw_text = self._extract_mcp_text(getattr(result, "content", None))
        if not raw_text:
            return {}

        payload = _parse_json_object(raw_text)
        if isinstance(payload, dict):
            if payload.get("ok") is False:
                return {}

            text = _first_text(payload.get("text"), payload.get("content"), raw_text)
            title = _first_text(
                payload.get("title"),
                getattr(result, "title", None),
                getattr(result, "name", None),
            )
            final_url = _first_text(
                payload.get("final_url"),
                payload.get("url"),
                getattr(result, "url", None),
            ) or url
            content_type = _first_text(
                payload.get("content_type"),
                getattr(result, "content_type", None),
            )
        else:
            text = raw_text
            title = _first_text(
                getattr(result, "title", None),
                getattr(result, "name", None),
            )
            final_url = _first_text(getattr(result, "url", None)) or url
            content_type = _first_text(getattr(result, "content_type", None))

        return self._normalize_result(
            url=url,
            final_url=final_url,
            title=title,
            text=text,
            content_type=content_type,
            status_code=None,
            source="playwright",
            retrieved_via=f"playwright_mcp:{tool_name}",
        )

    def _extract_mcp_text(self, content: Any) -> str:
        if not content:
            return ""

        parts: list[str] = []
        for item in content if isinstance(content, list) else [content]:
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

    def _build_mcp_headers(self, endpoint: str) -> dict[str, str]:
        parsed = urlparse(endpoint)
        headers: dict[str, str] = {}
        if parsed.hostname in {"localhost", "127.0.0.1"} and parsed.port == 3001:
            headers["Host"] = "localhost:3000"
        return headers

    def _read_via_local_playwright(
        self,
        url: str,
        *,
        selector: str = "body",
        wait_ms: int = 800,
        max_chars: int = 20_000,
    ) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return {}

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=int(self.timeout * 1000),
                    )
                    try:
                        page.wait_for_load_state(
                            "networkidle",
                            timeout=int(self.timeout * 1000),
                        )
                    except Exception:
                        pass

                    if wait_ms > 0:
                        page.wait_for_timeout(min(int(wait_ms), 10_000))

                    title = _first_text(page.title())
                    text = ""
                    try:
                        text = str(
                            page.locator(selector or "body").inner_text(
                                timeout=int(self.timeout * 1000)
                            )
                            or ""
                        )
                    except Exception:
                        text = str(page.content() or "")

                    return self._normalize_result(
                        url=url,
                        final_url=str(page.url or url),
                        title=title,
                        text=text[: max(1000, min(int(max_chars), 100_000))],
                        content_type="text/html",
                        status_code=None,
                        source="playwright",
                        retrieved_via="playwright_local",
                    )
                finally:
                    browser.close()
        except Exception:
            return {}

    def _normalize_result(
        self,
        *,
        url: str,
        final_url: str | None,
        title: str | None,
        text: str,
        content_type: str | None,
        status_code: int | None,
        source: str,
        retrieved_via: str,
    ) -> dict[str, Any]:
        cleaned_text = _normalize_text(text)
        return {
            "url": url,
            "final_url": final_url,
            "title": title or None,
            "text": cleaned_text,
            "content_type": content_type,
            "status_code": status_code,
            "source": source,
            "retrieved_via": retrieved_via,
            "text_length": len(cleaned_text),
        }


def _normalize_text(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _parse_json_object(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip()
    if not candidate.startswith("{") or not candidate.endswith("}"):
        return None
    try:
        payload = json.loads(candidate)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
