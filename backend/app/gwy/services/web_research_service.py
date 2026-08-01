from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
from app.gwy.services.web_fetch_service import WebFetchService
from app.gwy.services.web_search_service import WebSearchService


@dataclass(slots=True)
class WebResearchRequest:
    query: str
    position: dict[str, Any] | None = None
    planned_queries: list[str] = field(default_factory=list)
    seed_urls: list[str] = field(default_factory=list)
    top_k: int = 3
    max_queries: int = 3


@dataclass(slots=True)
class WebEvidence:
    title: str | None
    url: str
    final_url: str | None
    source_domain: str | None
    published_at: str | None
    retrieved_at: str
    excerpt: str
    evidence_type: str
    credibility: str
    retrieved_via: str
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "final_url": self.final_url,
            "source_domain": self.source_domain,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "excerpt": self.excerpt,
            "evidence_type": self.evidence_type,
            "credibility": self.credibility,
            "retrieved_via": self.retrieved_via,
            "text": self.text,
        }


@dataclass(slots=True)
class WebResearchResult:
    evidence: list[WebEvidence]
    failures: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    attempts: list[dict[str, Any]]
    insufficient_evidence: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence": [item.as_dict() for item in self.evidence],
            "citation_count": len(self.evidence),
            "failures": self.failures,
            "trace": self.trace,
            "attempts": self.attempts,
            "insufficient_evidence": self.insufficient_evidence,
        }


class WebResearchService:
    def __init__(
        self,
        *,
        search_service: Any | None = None,
        fetch_service: Any | None = None,
        browser_service: Any | None = None,
        max_results: int = 5,
        min_text_length: int | None = None,
    ) -> None:
        self.search_service = search_service or WebSearchService()
        self.fetch_service = fetch_service or WebFetchService()
        self.browser_service = browser_service or PlaywrightMCPService()
        self.max_results = max(1, max_results)
        self.min_text_length = max(
            0,
            min_text_length
            if min_text_length is not None
            else int(settings.WEB_FETCH_MIN_TEXT_LENGTH),
        )

    def verify(self, request: WebResearchRequest) -> WebResearchResult:
        trace: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        evidence: list[WebEvidence] = []
        attempts: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        started = time.perf_counter()
        queries = self._queries(request)
        self._trace(trace, "web_query_planned", {"query_count": len(queries)})

        for query_index, query in enumerate(queries, start=1):
            query_attempts = [query]
            retry_query = self._retry_query(query)
            if retry_query and retry_query != query:
                query_attempts.append(retry_query)
            for attempt_index, current_query in enumerate(query_attempts, start=1):
                self._trace(
                    trace,
                    "web_search_started",
                    {"query": current_query, "query_index": query_index, "attempt_index": attempt_index},
                )
                try:
                    hits = list(self.search_service.search(current_query, top_k=request.top_k) or [])
                except Exception as exc:
                    hits = []
                    failures.append({"query": current_query, "reason": "search_failed", "error": str(exc)})
                self._trace(
                    trace,
                    "web_search_completed",
                    {"query": current_query, "query_index": query_index, "attempt_index": attempt_index, "hit_count": len(hits)},
                )

                fetched_count = 0
                browser_fallback_count = 0
                for hit in self._prioritize_hits(hits):
                    url = str(hit.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    if not _is_safe_url(url):
                        failures.append({"url": url, "reason": _url_failure_reason(url)})
                        continue
                    if len(evidence) >= self.max_results:
                        break
                    before = len(trace)
                    item = self._retrieve_evidence(
                        hit=hit,
                        query=current_query,
                        trace=trace,
                        failures=failures,
                    )
                    fetched_count += 1
                    browser_fallback_count += sum(
                        1
                        for event in trace[before:]
                        if event.get("step") == "web_browser_fallback"
                    )
                    if item is not None:
                        evidence.append(item)
                attempts.append(
                    {
                        "query": current_query,
                        "query_index": query_index,
                        "attempt_index": attempt_index,
                        "hit_count": len(hits),
                        "fetched_count": fetched_count,
                        "browser_fallback_count": browser_fallback_count,
                        "is_retry": attempt_index > 1,
                    }
                )
                if hits or evidence:
                    break
            if len(evidence) >= self.max_results:
                break

        if not evidence and request.seed_urls:
            for url in request.seed_urls[: self.max_results]:
                if not _is_safe_url(url):
                    failures.append({"url": url, "reason": _url_failure_reason(url)})
                    continue
                item = self._retrieve_evidence(
                    hit={"url": url, "title": url},
                    query=request.query,
                    trace=trace,
                    failures=failures,
                )
                if item is not None:
                    evidence.append(item)

        self._trace(
            trace,
            "web_verification_completed",
            {
                "citation_count": len(evidence),
                "failure_count": len(failures),
                "insufficient_evidence": not bool(evidence),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return WebResearchResult(
            evidence=evidence,
            failures=failures,
            trace=trace,
            attempts=attempts,
            insufficient_evidence=not bool(evidence),
        )

    def _retry_query(self, query: str) -> str | None:
        normalized = str(query or "").strip()
        if not normalized or "官方公告" in normalized:
            return None
        return f"{normalized} 官方公告 招录简章 历年招录"

    def _retrieve_evidence(
        self,
        *,
        hit: dict[str, Any],
        query: str,
        trace: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> WebEvidence | None:
        url = str(hit.get("url") or "").strip()
        self._trace(trace, "web_page_fetch_started", {"url": url, "query": query})
        try:
            fetched = dict(self.fetch_service.fetch(url) or {})
        except Exception as exc:
            fetched = {}
            failures.append({"url": url, "reason": "fetch_failed", "error": str(exc)})
        self._trace(
            trace,
            "web_page_fetch_completed",
            {"url": url, "text_length": len(str(fetched.get("text") or ""))},
        )

        browser_result: dict[str, Any] = {}
        fetched_text = str(fetched.get("text") or "").strip()
        if not fetched_text or (
            len(fetched_text) < self.min_text_length
            and not bool(fetched.get("is_pdf"))
        ):
            self._trace(trace, "web_browser_fallback", {"url": url, "reason": "empty_or_short_http_text"})
            try:
                browser_result = dict(self.browser_service.read(url) or {})
            except Exception as exc:
                failures.append({"url": url, "reason": "browser_failed", "error": str(exc)})

        content = str(browser_result.get("text") or fetched_text).strip()
        if not content:
            failures.append({"url": url, "reason": "empty_page"})
            return None

        final_url = str(
            browser_result.get("final_url")
            or browser_result.get("url")
            or fetched.get("final_url")
            or url
        )
        retrieved_via = str(
            browser_result.get("retrieved_via")
            or fetched.get("retrieved_via")
            or "http"
        )
        title = str(
            browser_result.get("title")
            or fetched.get("title")
            or hit.get("title")
            or ""
        ).strip() or None
        evidence = WebEvidence(
            title=title,
            url=url,
            final_url=final_url,
            source_domain=urlparse(final_url).netloc.lower() or None,
            published_at=_first_text(hit.get("published_at"), fetched.get("published_at")),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            excerpt=content[:1000],
            evidence_type="pdf" if fetched.get("is_pdf") else "web_page",
            credibility=_credibility(final_url, retrieved_via),
            retrieved_via=retrieved_via,
            text=content,
        )
        self._trace(
            trace,
            "web_evidence_extracted",
            {"url": url, "source_domain": evidence.source_domain, "text_length": len(content)},
        )
        return evidence

    def _queries(self, request: WebResearchRequest) -> list[str]:
        values = [*request.planned_queries, request.query]
        result: list[str] = []
        for value in values:
            query = str(value or "").strip()
            if query and query not in result:
                result.append(query)
        return result[: max(1, min(request.max_queries, 5))]

    def _prioritize_hits(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            hits,
            key=lambda item: 0 if _is_official_domain(str(item.get("url") or "")) else 1,
        )

    def _trace(self, trace: list[dict[str, Any]], step: str, output: dict[str, Any]) -> None:
        trace.append({"step": step, "status": "done", "outputs_summary": output})


def _is_safe_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)


def _url_failure_reason(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return "unsupported_url_scheme"
    return "blocked_private_host"


def _is_official_domain(value: str) -> bool:
    hostname = (urlparse(value).hostname or "").lower()
    return hostname.endswith((".gov.cn", ".gov", ".edu.cn")) or hostname in {"gov.cn", "edu.cn"}


def _credibility(url: str, retrieved_via: str) -> str:
    if _is_official_domain(url) and retrieved_via:
        return "high"
    if retrieved_via in {"http", "fetch_mcp", "playwright_local"}:
        return "medium"
    return "low"


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None
