from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings


@dataclass(slots=True)
class PlaywrightMCPService:
    endpoint_url: str | None = None
    enabled: bool = True
    timeout: float = 15.0
    http_client: Any | None = None

    def __post_init__(self) -> None:
        if self.endpoint_url is None and settings.PLAYWRIGHT_MCP_URL is not None:
            self.endpoint_url = str(settings.PLAYWRIGHT_MCP_URL)
        self.timeout = self.timeout or 15.0

    def read(self, url: str) -> dict[str, Any]:
        normalized_url = str(url or "").strip()
        if not self.enabled or not normalized_url:
            return {}

        mcp_result = self._read_via_mcp(normalized_url)
        if mcp_result:
            return mcp_result

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
        priority_keywords = (
            "read",
            "snapshot",
            "page",
            "browser",
            "open",
            "navigate",
            "goto",
        )
        for tool in tools:
            name = str(getattr(tool, "name", "") or "").strip()
            if not name:
                continue
            lowered = name.lower()
            if any(keyword in lowered for keyword in priority_keywords):
                return name
        if not tools:
            return None
        fallback_name = str(getattr(tools[0], "name", "") or "").strip()
        return fallback_name or None

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
        if properties:
            first_key = next(iter(properties.keys()))
            return {first_key: url}
        return {"url": url}

    def _normalize_mcp_result(
        self,
        result: Any,
        url: str,
        tool_name: str,
    ) -> dict[str, Any]:
        text = self._extract_mcp_text(getattr(result, "content", None))
        if not text:
            return {}

        title = _first_text(
            getattr(result, "title", None),
            getattr(result, "name", None),
        )
        return self._normalize_result(
            url=url,
            final_url=_first_text(getattr(result, "url", None)) or url,
            title=title,
            text=text,
            content_type=_first_text(getattr(result, "content_type", None)),
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

    def _read_via_local_playwright(self, url: str) -> dict[str, Any]:
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

                    title = _first_text(page.title())
                    text = ""
                    try:
                        text = str(
                            page.locator("body").inner_text(
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
                        text=text,
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
