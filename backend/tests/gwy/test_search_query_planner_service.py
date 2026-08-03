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


def test_search_query_planner_expands_competition_query_to_official_candidates() -> None:
    planner = SearchQueryPlannerService(
        chat_service=FakeChatService(
            response='{"primary_query":"100110001001 2026 报录比 进面分 官方公告","planned_queries":["100110001001 2026 报录比","100110001001 进面分 官方公告","100110001001 site:gov.cn 招录 公告"],"required_source_kinds":["official"],"search_kind":"web","trace_notes":"优先官方来源"}'
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

    assert result.search_kind == "web"
    assert result.required_source_kinds == ["official"]
    assert result.primary_query.startswith("100110001001")
    assert any("官方公告" in item for item in result.planned_queries)


def test_search_query_planner_falls_back_when_llm_output_is_invalid() -> None:
    planner = SearchQueryPlannerService(
        chat_service=FakeChatService(response="not-json")
    )

    result = planner.plan(
        SearchQueryRequest(
            query="2026 进面分",
            search_kind="web",
            position={"department_name": "某部门", "job_title": "某岗位"},
        )
    )

    assert result.planned_queries
    assert "2026" in result.primary_query
    assert result.trace[-1]["strategy"] == "fallback_rules"
