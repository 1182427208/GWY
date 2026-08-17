from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from app.core.config import settings
from app.gwy.services.web_mcp_client import WebMCPClient


@dataclass(slots=True)
class WebSearchResult:
    title: str
    url: str | None
    snippet: str | None
    source: str = "searxng"


class WebSearchService:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        web_mcp_enabled: bool = True,
        base_url: str | None = None,
        timeout: float | None = None,
        language: str | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.enabled = settings.WEB_SEARCH_ENABLED if enabled is None else enabled
        self.web_mcp_enabled = web_mcp_enabled
        self.base_url = (base_url or settings.SEARXNG_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.SEARXNG_TIMEOUT_SECONDS
        self.language = language or settings.SEARXNG_LANGUAGE
        self.http_client = http_client

    def search(self, query: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip()
        if not self.enabled or not normalized_query:
            return []

        limit = max(1, top_k or settings.SEARXNG_TOP_K)
        if self.web_mcp_enabled and settings.WEB_MCP_URL is not None:
            mcp_result = WebMCPClient(endpoint_url=str(settings.WEB_MCP_URL)).search(
                normalized_query,
                top_k=limit,
            )
            results = list(mcp_result.get("results") or [])
            if results:
                return results[:limit]
        try:
            response = self._get_search_response(normalized_query)
            response.raise_for_status()
            results = self._parse_results(response.text, limit=limit)
            if results:
                return results
        except Exception:
            pass

        duckduckgo_results = self._search_duckduckgo(normalized_query, limit=limit)
        if duckduckgo_results:
            return duckduckgo_results

        return self._search_bing_via_playwright(normalized_query, limit=limit)

    def _get_search_response(self, query: str) -> httpx.Response:
        url = f"{self.base_url}/search?q={quote_plus(query)}"
        if self.language:
            url = f"{url}&language={quote_plus(self.language)}"

        headers = _default_headers()
        headers.update(_forwarded_headers(self.base_url))

        if self.http_client is not None:
            return self.http_client.get(url, timeout=self.timeout, headers=headers)

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            return client.get(url, headers=headers)

    def _parse_results(self, html_text: str, *, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for title, url, snippet in self._iter_searxng_results(html_text):
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": "searxng",
                }
            )
            if len(results) >= limit:
                break
        return results

    def _search_duckduckgo(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            response = self._get_duckduckgo_response(query)
            response.raise_for_status()
        except Exception:
            return []

        results: list[dict[str, Any]] = []
        for title, url, snippet in self._iter_duckduckgo_results(response.text):
            if not url or _is_advertisement_url(url):
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": "duckduckgo",
                }
            )
            if len(results) >= limit:
                break
        return results

    def _iter_searxng_results(
        self, html_text: str
    ) -> list[tuple[str, str | None, str | None]]:
        results: list[tuple[str, str | None, str | None]] = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        titles = [match for match in pattern.finditer(html_text)]
        snippets = [match for match in snippet_pattern.finditer(html_text)]
        for index, match in enumerate(titles):
            raw_title = _strip_tags(match.group("title"))
            raw_url = html.unescape(match.group("url"))
            snippet = None
            if index < len(snippets):
                snippet = _strip_tags(snippets[index].group("snippet"))
            title = html.unescape(raw_title).strip()
            url = _normalize_url(raw_url)
            if title:
                results.append((title, url, snippet))
        return results

    def _iter_duckduckgo_results(
        self, html_text: str
    ) -> list[tuple[str, str | None, str | None]]:
        results: list[tuple[str, str | None, str | None]] = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        titles = [match for match in pattern.finditer(html_text)]
        snippets = [match for match in snippet_pattern.finditer(html_text)]
        for index, match in enumerate(titles):
            raw_title = _strip_tags(match.group("title"))
            raw_url = html.unescape(match.group("url"))
            snippet = None
            if index < len(snippets):
                snippet = _strip_tags(snippets[index].group("snippet"))
            title = html.unescape(raw_title).strip()
            url = _normalize_duckduckgo_url(raw_url)
            if title:
                results.append((title, url, snippet))
        return results

    def _get_duckduckgo_response(self, query: str) -> httpx.Response:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        if self.http_client is not None:
            return self.http_client.get(url, timeout=self.timeout)

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            return client.get(url, headers=_default_headers())

    def _search_bing_via_playwright(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return []

        try:
            timeout_seconds = max(float(self.timeout or 0), 20.0)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    search_url = f"https://cn.bing.com/search?q={quote_plus(query)}"
                    page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=int(timeout_seconds * 1000),
                    )
                    try:
                        page.wait_for_load_state(
                            "networkidle",
                            timeout=int(timeout_seconds * 1000),
                        )
                    except Exception:
                        pass

                    results: list[dict[str, Any]] = []
                    cards = page.locator("li.b_algo")
                    for index in range(min(cards.count(), limit)):
                        card = cards.nth(index)
                        link = card.locator("h2 a").first
                        try:
                            title = _first_text(
                                link.inner_text(timeout=int(timeout_seconds * 1000))
                            )
                        except Exception:
                            title = None
                        try:
                            url = _normalize_url(link.get_attribute("href"))
                        except Exception:
                            url = None
                        snippet = None
                        try:
                            snippet = _first_text(
                                card.locator(".b_caption p").first.inner_text(
                                    timeout=int(timeout_seconds * 1000)
                                )
                            )
                        except Exception:
                            snippet = None

                        if title and url and not _is_advertisement_url(url):
                            results.append(
                                {
                                    "title": title,
                                    "url": url,
                                    "snippet": snippet,
                                    "source": "bing",
                                }
                            )
                    return results
                finally:
                    browser.close()
        except Exception:
            return []


def _normalize_url(url: Any) -> str | None:
    text = str(url or "").strip()
    return text or None


def _normalize_duckduckgo_url(url: Any) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    if text.startswith("//"):
        text = "https:" + text

    parsed = urlparse(text)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            return unquote(str(target)).strip() or None
    return _normalize_url(text)


def _is_advertisement_url(url: Any) -> bool:
    text = str(url or "").lower()
    return any(
        marker in text
        for marker in (
            "duckduckgo.com/y.js",
            "bing.com/aclick",
            "ad_domain=",
            "ad_provider=",
            "click_metadata=",
        )
    )


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }


def _forwarded_headers(base_url: str) -> dict[str, str]:
    parsed = urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return {}
    return {
        "X-Forwarded-For": "127.0.0.1",
        "X-Real-IP": "127.0.0.1",
        "X-Forwarded-Proto": parsed.scheme or "http",
    }


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()
