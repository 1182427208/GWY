from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.core.config import settings
from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
from app.gwy.services.web_mcp_client import WebMCPClient
from app.gwy.services.web_fetch_service import WebFetchService
from app.gwy.services.web_research_service import WebResearchRequest, WebResearchService
from app.gwy.services.web_search_service import WebSearchService


@dataclass
class DummyResponse:
    text: str = ""
    json_data: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return dict(self.json_data or {})


class DummyHttpClient:
    def __init__(self, response: DummyResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> DummyResponse:
        self.calls.append({"method": "get", "url": url, **kwargs})
        return self.response

    def post(self, url: str, **kwargs: Any) -> DummyResponse:
        self.calls.append({"method": "post", "url": url, **kwargs})
        return self.response


def test_web_search_service_parses_searxng_html_and_limits_results() -> None:
    html = """
    <html>
      <body>
        <article class="result">
          <h3><a class="result__a" href="https://example.com/a">Position A</a></h3>
          <a class="result__snippet">Snippet A</a>
        </article>
        <article class="result">
          <h3><a class="result__a" href="https://example.com/b">Position B</a></h3>
          <a class="result__snippet">Snippet B</a>
        </article>
        <article class="result">
          <h3><a class="result__a" href="https://example.com/c">Position C</a></h3>
          <a class="result__snippet">Snippet C</a>
        </article>
      </body>
    </html>
    """
    client = DummyHttpClient(DummyResponse(text=html))

    service = WebSearchService(
        enabled=True,
        base_url="http://localhost:8080",
        http_client=client,
    )
    results = service.search("公务员 岗位", top_k=2)

    assert len(results) == 2
    assert client.calls[0]["url"] == "http://localhost:8080/search?q=%E5%85%AC%E5%8A%A1%E5%91%98+%E5%B2%97%E4%BD%8D&language=zh-CN"
    assert client.calls[0]["headers"]["X-Forwarded-For"] == "127.0.0.1"
    assert results[0]["title"] == "Position A"
    assert results[0]["snippet"] == "Snippet A"
    assert results[0]["source"] == "searxng"


def test_web_search_service_falls_back_when_searxng_has_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DummyHttpClient(DummyResponse(text="<html><body></body></html>"))

    service = WebSearchService(
        enabled=True,
        base_url="https://searxng.example",
        http_client=client,
    )
    monkeypatch.setattr(
        service,
        "_search_duckduckgo",
        lambda query, limit: [
            {
                "title": "Fallback Title",
                "url": "https://example.com/fallback",
                "snippet": "Fallback Snippet",
                "source": "duckduckgo",
            }
        ],
    )

    results = service.search("Python", top_k=1)

    assert len(results) == 1
    assert results[0]["source"] == "duckduckgo"
    assert results[0]["title"] == "Fallback Title"


def test_web_search_service_falls_back_to_bing_for_chinese_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DummyHttpClient(DummyResponse(text="<html><body></body></html>"))

    service = WebSearchService(
        enabled=True,
        base_url="http://localhost:8080",
        http_client=client,
    )
    monkeypatch.setattr(service, "_search_duckduckgo", lambda query, limit: [])
    monkeypatch.setattr(
        service,
        "_search_bing_via_playwright",
        lambda query, limit: [
            {
                "title": "Bing Fallback Title",
                "url": "https://example.com/bing-fallback",
                "snippet": "Bing Fallback Snippet",
                "source": "bing",
            }
        ],
    )

    results = service.search("公务员 岗位", top_k=1)

    assert len(results) == 1
    assert results[0]["source"] == "bing"
    assert results[0]["title"] == "Bing Fallback Title"


def test_web_fetch_service_extracts_visible_text_from_html() -> None:
    client = DummyHttpClient(
        DummyResponse(
            text=(
                "<html><head><title>Notice Title</title>"
                "<script>ignore()</script></head>"
                "<body><h1>Main Title</h1><p>Paragraph one.</p><p>Paragraph two.</p></body></html>"
            ),
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    service = WebFetchService(http_client=client)
    result = service.fetch("https://example.com/notice")

    assert result["title"] == "Notice Title"
    assert "Main Title" in result["text"]
    assert "Paragraph one." in result["text"]
    assert "ignore" not in result["text"]
    assert result["source"] == "fetch"
    assert result["retrieved_via"] == "http"


def test_playwright_mcp_service_uses_mcp_result_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PlaywrightMCPService(endpoint_url="http://localhost:3001/mcp")
    monkeypatch.setattr(
        PlaywrightMCPService,
        "_read_via_mcp",
        lambda self, url: {
            "url": url,
            "final_url": url,
            "title": "Rendered Title",
            "text": "Rendered body content",
            "content_type": "text/html",
            "status_code": None,
            "source": "playwright",
            "retrieved_via": "playwright_mcp:read",
            "text_length": len("Rendered body content"),
        },
    )
    monkeypatch.setattr(
        PlaywrightMCPService,
        "_read_via_local_playwright",
        lambda self, url: pytest.fail(
            "local fallback should not run when MCP succeeds"
        ),
    )

    result = service.read("https://example.com/dynamic")

    assert result["title"] == "Rendered Title"
    assert result["retrieved_via"] == "playwright_mcp:read"


def test_playwright_mcp_service_falls_back_to_local_playwright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PlaywrightMCPService(endpoint_url="http://localhost:3001/mcp")
    monkeypatch.setattr(PlaywrightMCPService, "_read_via_mcp", lambda self, url: {})
    monkeypatch.setattr(
        PlaywrightMCPService,
        "_read_via_local_playwright",
        lambda self, url: {
            "url": url,
            "final_url": url,
            "title": "Local Title",
            "text": "Local body content",
            "content_type": "text/html",
            "status_code": None,
            "source": "playwright",
            "retrieved_via": "playwright_local",
            "text_length": len("Local body content"),
        },
    )

    result = service.read("https://example.com/dynamic")

    assert result["title"] == "Local Title"
    assert result["retrieved_via"] == "playwright_local"


def test_web_search_service_prefers_unified_web_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(
        WebMCPClient,
        "search",
        lambda self, query, top_k=5: {
            "query": query,
            "results": [
                {
                    "title": "Remote Search",
                    "url": "https://example.com/remote",
                    "snippet": "Remote snippet",
                    "source": "web_mcp",
                }
            ],
        },
    )

    service = WebSearchService(web_mcp_enabled=True, http_client=DummyHttpClient(DummyResponse(text="")))
    results = service.search("统一 MCP", top_k=1)

    assert len(results) == 1
    assert results[0]["title"] == "Remote Search"
    assert results[0]["source"] == "web_mcp"


def test_web_fetch_service_prefers_unified_web_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(
        WebMCPClient,
        "fetch",
        lambda self, url, max_chars=20000: {
            "url": url,
            "final_url": url,
            "title": "Remote Title",
            "text": "Remote body",
            "content_type": "text/html",
            "status_code": 200,
            "retrieved_via": "fetch_mcp",
            "is_pdf": False,
        },
    )

    service = WebFetchService(http_client=DummyHttpClient(DummyResponse(text="")))
    result = service.fetch("https://example.com/remote-page")

    assert result["title"] == "Remote Title"
    assert result["retrieved_via"] == "fetch_mcp"


def test_playwright_mcp_service_prefers_unified_web_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(
        WebMCPClient,
        "read",
        lambda self, url, selector="body", wait_ms=800, max_chars=20000: {
            "url": url,
            "final_url": url,
            "title": "Remote Rendered",
            "text": "Remote rendered content",
            "content_type": "text/html",
            "status_code": 200,
            "retrieved_via": "web_mcp:browser_retrieve",
        },
    )

    service = PlaywrightMCPService(endpoint_url="", web_mcp_enabled=True)
    result = service.read("https://example.com/dynamic")

    assert result["title"] == "Remote Rendered"
    assert result["retrieved_via"] == "web_mcp:browser_retrieve"


def test_web_research_service_prefers_unified_web_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(
        WebMCPClient,
        "verify",
        lambda self, query, planned_queries=None, top_k=3, seed_urls=None: {
            "evidence": [
                {
                    "title": "Policy Notice",
                    "url": "https://gov.example/notice",
                    "final_url": "https://gov.example/notice",
                    "source_domain": "gov.example",
                    "published_at": "2026-08-02T00:00:00Z",
                    "retrieved_at": "2026-08-02T00:00:01Z",
                    "excerpt": "Evidence snippet",
                    "evidence_type": "web_page",
                    "credibility": "high",
                    "retrieved_via": "web_mcp",
                    "text": "Evidence body",
                }
            ],
            "failures": [],
            "trace": [{"step": "remote", "status": "done"}],
            "attempts": [{"query": query, "hit_count": 1}],
            "insufficient_evidence": False,
        },
    )

    service = WebResearchService(web_mcp_enabled=True)
    result = service.verify(
        WebResearchRequest(
            query="统一 MCP 改造",
            planned_queries=["统一 MCP"],
            seed_urls=["https://gov.example/notice"],
            top_k=1,
        )
    )

    assert result.evidence[0].title == "Policy Notice"
    assert result.trace[0]["step"] == "remote"
