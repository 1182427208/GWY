from __future__ import annotations

from typing import Any

from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
from app.gwy.services.web_fetch_service import WebFetchService
from app.gwy.services.web_search_service import WebSearchService


def search_web_mcp(query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
    return WebSearchService().search(query_text, top_k=top_k)


def fetch_web_page_mcp(url: str) -> dict[str, Any]:
    return WebFetchService().fetch(url)


def read_web_page_playwright_mcp(url: str) -> dict[str, Any]:
    return PlaywrightMCPService().read(url)
