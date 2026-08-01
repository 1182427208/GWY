from __future__ import annotations

from typing import Any

from app.gwy.services.web_research_service import WebResearchRequest, WebResearchService


class FakeSearchService:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.results[:top_k or len(self.results)]


class FakeFetchService:
    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results

    def fetch(self, url: str) -> dict[str, Any]:
        return self.results.get(url, {})


class FakeBrowserService:
    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results

    def read(self, url: str) -> dict[str, Any]:
        return self.results.get(url, {})


def test_verify_web_evidence_normalizes_fetched_results() -> None:
    service = WebResearchService(
        search_service=FakeSearchService([{"url": "https://notice.gov.cn/a", "title": "官方公告"}]),
        fetch_service=FakeFetchService({"https://notice.gov.cn/a": {"title": "官方公告", "text": "报名条件"}}),
        browser_service=FakeBrowserService({}),
        min_text_length=100,
    )

    result = service.verify(WebResearchRequest(query="报名条件"))

    assert result.insufficient_evidence is False
    assert result.evidence[0].source_domain == "notice.gov.cn"
    assert result.evidence[0].excerpt == "报名条件"
    assert result.evidence[0].credibility == "high"
    assert result.trace[-1]["step"] == "web_verification_completed"


def test_verify_web_evidence_uses_browser_for_short_http_text() -> None:
    service = WebResearchService(
        search_service=FakeSearchService([{"url": "https://example.com/js", "title": "动态页面"}]),
        fetch_service=FakeFetchService({"https://example.com/js": {"text": ""}}),
        browser_service=FakeBrowserService(
            {"https://example.com/js": {"text": "动态内容", "retrieved_via": "playwright_local"}}
        ),
        min_text_length=100,
    )

    result = service.verify(WebResearchRequest(query="动态页面"))

    assert result.evidence[0].text == "动态内容"
    assert result.evidence[0].retrieved_via == "playwright_local"
    assert any(item["step"] == "web_browser_fallback" for item in result.trace)


def test_verify_web_evidence_rejects_unsafe_urls() -> None:
    service = WebResearchService(search_service=FakeSearchService([]))

    result = service.verify(
        WebResearchRequest(query="x", seed_urls=["file:///secret.txt", "http://127.0.0.1:8000"])
    )

    assert result.evidence == []
    assert result.insufficient_evidence is True
    assert {item["reason"] for item in result.failures} == {
        "unsupported_url_scheme",
        "blocked_private_host",
    }
