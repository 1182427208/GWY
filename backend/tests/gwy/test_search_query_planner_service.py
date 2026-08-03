from __future__ import annotations

from typing import Any

from app.gwy.services.search_query_planner_service import (
    SearchQueryPlannerService,
    SearchQueryRequest,
)


class FakeChatService:
    def __init__(self, *, response: str) -> None:
        self.response = response
        self.messages: list[dict[str, Any]] | None = None

    def chat_completion(self, messages: list[dict[str, Any]], **_: Any) -> str:
        self.messages = messages
        return self.response


def test_search_query_planner_emits_distinct_trace_steps_for_llm_path() -> None:
    planner = SearchQueryPlannerService(
        chat_service=FakeChatService(
            response=(
                '{"primary_query":"100110001001 2026 报录比 进面分 官方公告",'
                '"planned_queries":['
                '"100110001001 2026 报录比 官方公告",'
                '"100110001001 进面分 官方公告",'
                '"100110001001 site:gov.cn 招录 公告"],'
                '"required_source_kinds":["official"],'
                '"search_kind":"web",'
                '"trace_notes":"prefer official sources"}'
            )
        )
    )

    result = planner.plan(
        SearchQueryRequest(
            query="100110001001 2026报录比 进面人数 进面分",
            search_kind="web",
            position={
                "position_code": "100110001001",
                "department_name": "中央办公厅",
                "job_title": "法务管理岗位一级主任科员及以下",
            },
        )
    )

    assert [entry["step"] for entry in result.trace] == [
        "search_query_planning_started",
        "search_query_rewritten",
        "search_query_finalized",
    ]
    assert result.trace[0]["input"]["original_query"] == "100110001001 2026报录比 进面人数 进面分"
    assert result.trace[1]["output"]["original_query"] == "100110001001 2026报录比 进面人数 进面分"
    assert result.trace[1]["output"]["primary_query"] == "100110001001 2026 报录比 进面分 官方公告"
    assert result.planned_queries[0] == "100110001001 2026 报录比 进面分 官方公告"
    assert result.trace[2]["tool"] == "web_search"
    assert result.required_source_kinds == ["official"]


def test_search_query_planner_fallback_keeps_original_query_when_candidates_are_full() -> None:
    planner = SearchQueryPlannerService(chat_service=FakeChatService(response="not-json"))
    request = SearchQueryRequest(
        query="2026 进面分",
        search_kind="web",
        planned_queries=[
            "候选一",
            "候选二",
            "候选三",
            "候选四",
            "候选五",
        ],
        position={"department_name": "某部门", "job_title": "某岗位"},
    )

    result = planner.plan(request)

    assert result.planned_queries[0] == "2026 进面分"
    assert "2026 进面分" in result.planned_queries
    assert "候选一" in result.planned_queries
    assert [entry["step"] for entry in result.trace] == [
        "search_query_planning_started",
        "search_query_rewrite_failed",
        "search_query_finalized",
    ]
    assert result.trace[1]["error"] == "planner response must be valid JSON"
    assert result.trace[2]["output"]["strategy"] == "fallback_rules"


def test_search_query_planner_preserves_original_query_when_llm_output_is_invalid() -> None:
    planner = SearchQueryPlannerService(chat_service=FakeChatService(response="not-json"))

    result = planner.plan(
        SearchQueryRequest(
            query="2026 进面分",
            search_kind="web",
            position={"department_name": "某部门", "job_title": "某岗位"},
        )
    )

    assert result.planned_queries[0] == "2026 进面分"
    assert result.primary_query == "2026 进面分"
