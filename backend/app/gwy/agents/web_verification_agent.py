from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
from app.gwy.services.web_fetch_service import WebFetchService
from app.gwy.services.web_search_service import WebSearchService


class WebVerificationState(TypedDict, total=False):
    position: dict[str, Any]
    history_summary: dict[str, Any]
    history_records: list[dict[str, Any]]
    scope: dict[str, Any]
    planned_queries: list[str]
    research_targets: list[dict[str, Any]]
    search_queries: list[str]
    web_results: list[dict[str, Any]]
    web_search_attempts: list[dict[str, Any]]
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class WebVerificationAgent:
    web_search_service: WebSearchService | None = None
    web_fetch_service: WebFetchService | None = None
    browser_service: PlaywrightMCPService | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.web_search_service = self.web_search_service or WebSearchService()
        self.web_fetch_service = self.web_fetch_service or WebFetchService()
        self.browser_service = self.browser_service or PlaywrightMCPService()
        self.graph = self._build_graph()

    def run(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]] | None = None,
        scope: dict[str, Any],
        planned_queries: list[str] | None = None,
        research_targets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        state: WebVerificationState = {
            "position": dict(position or {}),
            "history_summary": dict(history_summary or {}),
            "history_records": list(history_records or []),
            "scope": dict(scope or {}),
            "planned_queries": list(planned_queries or []),
            "research_targets": list(research_targets or []),
            "trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self) -> Any:
        builder = StateGraph(WebVerificationState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("search", self._node_search)
        builder.add_node("observe", self._node_observe)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "search")
        builder.add_edge("search", "observe")
        builder.add_edge("observe", END)
        return builder.compile()

    def _node_plan(self, state: WebVerificationState) -> dict[str, Any]:
        position = dict(state.get("position") or {})
        history_summary = dict(state.get("history_summary") or {})
        history_records = list(state.get("history_records") or [])
        scope = dict(state.get("scope") or {})
        research_targets = list(state.get("research_targets") or [])

        if research_targets:
            queries = self._deduplicate_texts(
                self._build_queries_from_targets(
                    position=position,
                    history_summary=history_summary,
                    history_records=history_records,
                    scope=scope,
                    research_targets=research_targets,
                )
            )
        else:
            queries = self._deduplicate_texts(
                [
                    *list(state.get("planned_queries") or []),
                    *self._build_web_search_queries(
                        position=position,
                        history_summary=history_summary,
                        scope=scope,
                    ),
                ]
            )

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "web_verification_plan",
                "status": "done",
                "detail": "先按缺失年份和字段拆分检索目标，再逐条检索对应证据。",
                "query_count": len(queries),
                "target_count": len(research_targets),
                "inputs_summary": {
                    "position_label": " / ".join(
                        part
                        for part in [
                            str(position.get("department_name") or "").strip(),
                            str(position.get("office_name") or "").strip(),
                            str(position.get("job_title") or "").strip(),
                        ]
                        if part
                    ),
                    "history_record_count": int(history_summary.get("record_count") or 0),
                    "year": scope.get("year"),
                },
                "outputs_summary": {
                    "query_count": len(queries),
                    "first_query": queries[0] if queries else "",
                    "target_count": len(research_targets),
                },
            }
        )
        return {"search_queries": queries, "trace": trace}

    def _node_search(self, state: WebVerificationState) -> dict[str, Any]:
        position = dict(state.get("position") or {})
        history_summary = dict(state.get("history_summary") or {})
        scope = dict(state.get("scope") or {})
        queries = list(state.get("search_queries") or [])

        results: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        trace = list(state.get("trace") or [])
        seen_urls: set[str] = set()

        for query_index, query in enumerate(queries[:3], start=1):
            query_attempts = [query]
            retry_query = self._build_web_retry_query(query)
            if retry_query and retry_query != query:
                query_attempts.append(retry_query)

            for attempt_index, current_query in enumerate(query_attempts, start=1):
                attempt_started = time.perf_counter()
                hits = self.web_search_service.search(current_query, top_k=3)
                attempt_results: list[dict[str, Any]] = []
                browser_fallback_count = 0
                fetched_count = 0

                for hit in hits:
                    url = str(hit.get("url") or "").strip()
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    fetched = self._fetch_web_page(url)
                    fetched_count += 1
                    browser_result = {}
                    if self._needs_browser_fallback(fetched):
                        browser_result = self._read_with_browser(url)
                        if browser_result:
                            browser_fallback_count += 1
                    merged_content = self._merge_web_content(hit, fetched, browser_result)
                    attempt_results.append(
                        {
                            "query": current_query,
                            "title": hit.get("title"),
                            "url": hit.get("url"),
                            "snippet": hit.get("snippet"),
                            "source": hit.get("source") or "web",
                            "content": merged_content.get("content"),
                            "content_type": merged_content.get("content_type"),
                            "retrieved_via": merged_content.get("retrieved_via"),
                            "final_url": merged_content.get("final_url"),
                            "is_pdf": merged_content.get("is_pdf", False),
                            "attempt_index": attempt_index,
                            "query_index": query_index,
                        }
                    )

                results.extend(attempt_results)
                attempts.append(
                    {
                        "query": current_query,
                        "query_index": query_index,
                        "attempt_index": attempt_index,
                        "hit_count": len(attempt_results),
                        "fetched_count": fetched_count,
                        "browser_fallback_count": browser_fallback_count,
                        "is_retry": attempt_index > 1,
                    }
                )
                trace.append(
                    {
                        "step": "web_verification_search",
                        "status": "done" if attempt_results else "retry",
                        "detail": (
                            f"第 {query_index} 组检索词命中 {len(attempt_results)} 条结果；"
                            f"抓取 {fetched_count} 个页面，"
                            f"浏览器回填 {browser_fallback_count} 次。"
                        ),
                        "query": current_query,
                        "query_index": query_index,
                        "attempt_index": attempt_index,
                        "hit_count": len(attempt_results),
                        "fetched_count": fetched_count,
                        "browser_fallback_count": browser_fallback_count,
                        "elapsed_ms": int((time.perf_counter() - attempt_started) * 1000),
                        "inputs_summary": {
                            "query": current_query,
                            "query_index": query_index,
                            "attempt_index": attempt_index,
                        },
                        "outputs_summary": {
                            "hit_count": len(attempt_results),
                            "fetched_count": fetched_count,
                            "browser_fallback_count": browser_fallback_count,
                        },
                        "evidence_refs": [
                            {
                                "id": str(hit.get("url") or hit.get("final_url") or ""),
                                "doc_title": str(hit.get("title") or hit.get("source") or ""),
                                "source_file": str(hit.get("source") or "web"),
                                "content": str(
                                    hit.get("snippet")
                                    or hit.get("content")
                                    or ""
                                )[:220],
                                "score": 0,
                            }
                            for hit in attempt_results[:2]
                        ],
                    }
                )
                if attempt_results:
                    break

        return {
            "web_results": results[:5],
            "web_search_attempts": attempts,
            "trace": trace,
            "position": position,
            "history_summary": history_summary,
            "scope": scope,
        }

    def _node_observe(self, state: WebVerificationState) -> dict[str, Any]:
        results = list(state.get("web_results") or [])
        attempts = list(state.get("web_search_attempts") or [])
        browser_fallback_count = sum(
            int(item.get("browser_fallback_count") or 0) for item in attempts
        )
        retry_count = sum(1 for item in attempts if item.get("is_retry"))

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "web_verification_observe",
                "status": "done",
                "detail": (
                    "整理外网补证结果，确认是否需要重试，并统计浏览器回填情况。"
                ),
                "result_count": len(results),
                "retry_count": retry_count,
                "browser_fallback_count": browser_fallback_count,
                "inputs_summary": {
                    "result_count": len(results),
                    "attempt_count": len(attempts),
                },
                "outputs_summary": {
                    "retry_count": retry_count,
                    "browser_fallback_count": browser_fallback_count,
                },
            }
        )
        return {
            "web_results": results,
            "web_search_attempts": attempts,
            "trace": trace,
        }

    def _build_web_search_queries(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        scope: dict[str, Any],
    ) -> list[str]:
        department_name = str(position.get("department_name") or "").strip()
        office_name = str(position.get("office_name") or "").strip()
        job_title = str(position.get("job_title") or "").strip()
        position_code = str(position.get("position_code") or "").strip()
        year = str(scope.get("year") or "").strip()
        scope_query = str(scope.get("query") or "").strip()

        queries = [
            " ".join(
                part
                for part in [scope_query, department_name, office_name, job_title, position_code]
                if part
            ).strip(),
            " ".join(
                part
                for part in [
                    department_name,
                    office_name,
                    job_title,
                    position_code,
                    "报录比",
                    "竞争比",
                    "历年",
                    "招考简章",
                ]
                if part
            ).strip(),
            " ".join(
                part
                for part in [
                    department_name,
                    job_title,
                    year,
                    "招录人数",
                    "进面分",
                ]
                if part
            ).strip(),
        ]
        if history_summary.get("record_count", 0) == 0:
            queries.append(
                " ".join(
                    part
                    for part in [
                        department_name,
                        office_name,
                        job_title,
                        "报录比",
                        "历年招录",
                    ]
                    if part
                ).strip()
            )
        return [query for query in queries if query]

    def _build_queries_from_targets(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]],
        scope: dict[str, Any],
        research_targets: list[dict[str, Any]],
    ) -> list[str]:
        position_label = self._format_position_label(position)
        fallback_year = str(scope.get("year") or "").strip()
        queries: list[str] = []

        for target in research_targets:
            year = str(target.get("year") or fallback_year or "").strip()
            missing_field = str(target.get("missing_field") or "").strip()
            base_query = self._build_target_query_base(
                position_label=position_label,
                year=year,
                missing_field=missing_field,
                history_summary=history_summary,
                history_records=history_records,
            )
            if base_query:
                queries.append(base_query)
            for extra in list(target.get("queries") or [])[:2]:
                extra_query = str(extra or "").strip()
                if extra_query:
                    queries.append(extra_query)

        if not queries and history_summary.get("record_count", 0) == 0:
            queries.append(
                " ".join(
                    part
                    for part in [
                        position_label,
                        fallback_year,
                        "招考简章",
                        "官方公告",
                        "招录人数",
                        "报录比",
                    ]
                    if part
                ).strip()
            )

        return [query for query in queries if query]

    def _build_target_query_base(
        self,
        *,
        position_label: str,
        year: str,
        missing_field: str,
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]],
    ) -> str:
        if missing_field == "recruit_count":
            return " ".join(
                part
                for part in [
                    position_label,
                    year,
                    "招录人数",
                    "招考简章",
                    "官方公告",
                ]
                if part
            ).strip()
        if missing_field == "interview_ratio":
            return " ".join(
                part
                for part in [
                    position_label,
                    year,
                    "报录比",
                    "进面分",
                    "面试名单",
                    "官方公告",
                ]
                if part
            ).strip()
        if missing_field == "interview_score":
            return " ".join(
                part
                for part in [
                    position_label,
                    year,
                    "最低进面分",
                    "面试分数线",
                    "进面名单",
                ]
                if part
            ).strip()
        if missing_field == "history_sparse":
            return " ".join(
                part
                for part in [
                    position_label,
                    year,
                    "历年招录",
                    "招录人数",
                    "报录比",
                    "进面分",
                ]
                if part
            ).strip()
        if history_summary.get("record_count", 0) == 0 or not history_records:
            return " ".join(
                part
                for part in [
                    position_label,
                    year,
                    "招录人数",
                    "报录比",
                    "进面分",
                ]
                if part
            ).strip()
        return " ".join(
            part
            for part in [
                position_label,
                year,
                "招录人数",
                "报录比",
            ]
            if part
        ).strip()

    def _build_web_retry_query(self, query: str) -> str | None:
        normalized = str(query or "").strip()
        if not normalized:
            return None
        retry_suffix = " 官方公告 招考简章 历年 招录人数 报录比"
        if retry_suffix.strip() in normalized:
            return None
        return f"{normalized}{retry_suffix}"

    def _fetch_web_page(self, url: str) -> dict[str, Any]:
        if self.web_fetch_service is None or not url:
            return {}
        return dict(self.web_fetch_service.fetch(url) or {})

    def _read_with_browser(self, url: str) -> dict[str, Any]:
        if self.browser_service is None or not url:
            return {}
        return dict(self.browser_service.read(url) or {})

    def _needs_browser_fallback(self, fetched: dict[str, Any]) -> bool:
        if not fetched:
            return False
        text = str(fetched.get("text") or "").strip()
        if not text:
            return True
        if len(text) < 200 and not bool(fetched.get("is_pdf")):
            return True
        content_type = str(fetched.get("content_type") or "").lower()
        return "html" in content_type and "rendered" not in str(
            fetched.get("retrieved_via") or ""
        )

    def _merge_web_content(
        self,
        hit: dict[str, Any],
        fetched: dict[str, Any],
        browser_result: dict[str, Any],
    ) -> dict[str, Any]:
        browser_text = str(browser_result.get("text") or "").strip()
        fetched_text = str(fetched.get("text") or "").strip()
        content = browser_text or fetched_text or str(hit.get("snippet") or "").strip()
        retrieved_via = (
            browser_result.get("retrieved_via")
            or fetched.get("retrieved_via")
            or hit.get("source")
            or "web"
        )
        title = (
            browser_result.get("title")
            or fetched.get("title")
            or hit.get("title")
            or ""
        )
        return {
            "content": content,
            "content_type": browser_result.get("content_type")
            or fetched.get("content_type"),
            "retrieved_via": retrieved_via,
            "final_url": browser_result.get("url")
            or fetched.get("final_url")
            or hit.get("url"),
            "title": title,
            "is_pdf": bool(fetched.get("is_pdf")),
        }

    def _build_web_retry_query(self, query: str) -> str | None:
        normalized = str(query or "").strip()
        if not normalized or "瀹樻柟鍏憡" in normalized:
            return None
        suffix = self._build_target_retry_suffix(normalized)
        if not suffix:
            return None
        return f"{normalized}{suffix}"

    def _build_target_retry_suffix(self, query: str) -> str:
        joined = " ".join(
            token for token in str(query or "").split() if token and not token.isdigit()
        )
        if any(keyword in joined for keyword in ("进面分", "面试名单", "面试分")):
            return " 官方公告 面试名单 进面分"
        if any(keyword in joined for keyword in ("报录比", "竞争比", "竞争热度")):
            return " 官方公告 报录比 竞争比"
        if any(keyword in joined for keyword in ("招录人数", "招考人数", "录用人数")):
            return " 官方公告 招录人数"
        return " 官方公告 招考简章"

    def _deduplicate_texts(self, values: list[str]) -> list[str]:
        deduplicated: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            deduplicated.append(item)
        return deduplicated

    def _format_position_label(self, position: dict[str, Any]) -> str:
        return " / ".join(
            part
            for part in [
                str(position.get("department_name") or "").strip(),
                str(position.get("office_name") or "").strip(),
                str(position.get("job_title") or "").strip(),
            ]
            if part
        ) or "未知岗位"
