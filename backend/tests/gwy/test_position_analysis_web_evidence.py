from __future__ import annotations

from typing import Any

from app.gwy.agents.position_analysis_agent import PositionAnalysisAgent


class FakeEmbeddingService:
    def embed_text(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeRerankService:
    def rerank(
        self,
        query: str,
        documents: list[dict[str, object]],
        top_n: int = 5,
    ) -> list[dict[str, object]]:
        return list(documents)[:top_n]


class FakeMilvusStore:
    def search(
        self,
        query_vector: list[float],
        filter_expr: str | None,
        top_k: int = 10,
    ) -> list[dict[str, object]]:
        return []


class FakeRiskReviewAgent:
    def run(
        self,
        *,
        query: str,
        recommendations: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "risk_level": "low",
            "need_manual_confirm": False,
            "risk_items": [],
            "trace": [],
        }


class FakeReportGeneratorAgent:
    def run(
        self,
        *,
        title: str,
        recommendations: list[dict[str, object]],
        risk_review: dict[str, object],
    ) -> dict[str, object]:
        return {"outline": [], "report": "", "trace": []}


class RetryingWebSearchService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
        self.queries.append(query)
        if len(self.queries) == 1:
            return []
        return [
            {
                "title": "官方公告",
                "url": f"https://example.com/notice-{len(self.queries)}",
                "snippet": "岗位公告摘要",
                "source": "searxng",
            }
        ]


class RecordingWebFetchService:
    def fetch(self, url: str) -> dict[str, Any]:
        return {
            "url": url,
            "final_url": url,
            "title": "公告标题",
            "text": "短正文",
            "content_type": "text/html",
            "status_code": 200,
            "source": "fetch",
            "retrieved_via": "http",
            "is_pdf": False,
        }


class RecordingBrowserService:
    def read(self, url: str) -> dict[str, Any]:
        return {
            "url": url,
            "final_url": url,
            "title": "渲染后公告标题",
            "text": "浏览器渲染后的正文内容",
            "content_type": "text/html",
            "status_code": None,
            "source": "playwright",
            "retrieved_via": "playwright_local",
        }


class FakeChatService:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def chat_completion(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        return self.payload


def test_position_analysis_uses_llm_planned_web_targets() -> None:
    agent = PositionAnalysisAgent(
        session=None,
        embedding_service=FakeEmbeddingService(),
        rerank_service=FakeRerankService(),
        milvus_store=FakeMilvusStore(),
        chat_service=FakeChatService(
            """
            {
              "summary": "只补 2025 年进面分缺口",
              "targets": [
                {
                  "year": "2025",
                  "missing_field": "interview_score",
                  "needs_web_search": true,
                  "priority": "high",
                  "focus": ["2025 进面分", "面试名单"],
                  "search_queries": ["2025 进面分"],
                  "retry_queries": ["2025 面试最低分"],
                  "observation_questions": ["2025 年是否能查到进面分？"],
                  "evidence_focus": ["进面分", "面试名单"],
                  "reason": "2025 年缺少进面分"
                }
              ]
            }
            """
        ),
        web_search_service=RetryingWebSearchService(),
        web_fetch_service=RecordingWebFetchService(),
        browser_service=RecordingBrowserService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
    )

    targets = agent._build_web_research_targets(
        position={
            "department_name": "国家税务总局",
            "office_name": "第一税务分局",
            "job_title": "综合管理岗",
            "position_code": "2026-001",
        },
        history_summary={
            "record_count": 2,
            "history_years": [2024, 2025],
            "latest_recruit_count": 2,
            "latest_interview_ratio": None,
            "notes": ["2025 缺少进面数据"],
        },
        history_records=[
            {"year": 2024, "recruit_count": 2, "interview_ratio": "45:1"},
            {"year": 2025, "recruit_count": 2, "interview_ratio": None},
        ],
        scope={"year": 2026, "analysis_goal": "岗位逐项补证"},
        strategy_target={},
    )

    assert len(targets) == 1
    assert targets[0]["year"] == "2025"
    assert targets[0]["missing_field"] == "interview_score"
    assert "2025 进面分" in targets[0]["search_queries"]


def test_web_verification_prefers_research_targets_over_generic_queries() -> None:
    class RecordingSearchService:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
            self.queries.append(query)
            return [
                {
                    "title": "2025 年面试名单",
                    "url": "https://example.com/interview-list",
                    "snippet": "面试名单与进面分",
                    "source": "searxng",
                }
            ]

    search_service = RecordingSearchService()
    agent = PositionAnalysisAgent(
        session=None,
        embedding_service=FakeEmbeddingService(),
        rerank_service=FakeRerankService(),
        milvus_store=FakeMilvusStore(),
        web_search_service=search_service,
        web_fetch_service=RecordingWebFetchService(),
        browser_service=RecordingBrowserService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
    )

    position = {
        "department_name": "国家税务总局",
        "office_name": "第一税务分局",
        "job_title": "综合管理岗",
        "position_code": "2026-001",
    }
    history_summary = {
        "record_count": 2,
        "history_years": [2024, 2025],
        "recruit_count_trend": "stable",
        "interview_ratio_trend": "rising",
        "latest_recruit_count": 2,
        "latest_interview_ratio": None,
        "notes": ["2025 年缺少进面数据"],
    }
    scope = {
        "analysis_goal": "岗位逐项补证",
        "year": 2026,
        "profile_summary": {"major": "计算机类"},
    }
    research_targets = [
        {
            "year": "2025",
            "missing_field": "interview_score",
            "position_label": "国家税务总局 / 第一税务分局 / 综合管理岗",
            "queries": ["2025 进面分", "2025 面试最低分"],
            "focus": ["进面分", "面试名单"],
            "priority": "high",
        }
    ]

    agent.web_verification_agent.run(
        position=position,
        history_summary=history_summary,
        history_records=[],
        scope=scope,
        planned_queries=["国家税务总局 2026 招录人数 报录比"],
        research_targets=research_targets,
    )

    assert search_service.queries
    assert any("2025" in query and "进面分" in query for query in search_service.queries)
    assert not any("招录人数" in query or "报录比" in query for query in search_service.queries)


def test_search_web_evidence_uses_browser_fallback_and_keeps_query_context() -> None:
    agent = PositionAnalysisAgent(
        session=None,
        embedding_service=FakeEmbeddingService(),
        rerank_service=FakeRerankService(),
        milvus_store=FakeMilvusStore(),
        web_search_service=RetryingWebSearchService(),
        web_fetch_service=RecordingWebFetchService(),
        browser_service=RecordingBrowserService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
    )

    position = {
        "department_name": "国家税务总局",
        "office_name": "第一税务分局",
        "job_title": "综合管理岗",
        "position_code": "2026-001",
    }
    history_summary = {
        "record_count": 1,
        "history_years": [2024, 2025],
        "recruit_count_trend": "stable",
        "interview_ratio_trend": "rising",
        "latest_recruit_count": 2,
        "latest_interview_ratio": 45.0,
        "notes": ["历史数据可用"],
    }
    scope = {
        "analysis_goal": "岗位逐项分析",
        "year": 2026,
        "profile_summary": {"major": "计算机类"},
    }

    results = agent._search_web_evidence(
        position=position,
        history_summary=history_summary,
        scope=scope,
    )

    assert len(results["results"]) >= 1
    assert results["results"][0]["content"] == "浏览器渲染后的正文内容"
    assert results["results"][0]["retrieved_via"] == "playwright_local"
    assert len(results["attempts"]) >= 2
    assert results["attempts"][0]["is_retry"] is False
    assert results["attempts"][1]["is_retry"] is True
    assert any(item["status"] == "retry" for item in results["trace"])
    assert "国家税务总局" in agent.web_search_service.queries[0]
    assert "2026-001" in agent.web_search_service.queries[0]
    assert len(agent.web_search_service.queries) >= 2
    assert agent.web_search_service.queries[0] != agent.web_search_service.queries[1]


def test_build_web_search_queries_prioritizes_competition_scores_when_missing() -> None:
    agent = PositionAnalysisAgent(
        session=None,
        embedding_service=FakeEmbeddingService(),
        rerank_service=FakeRerankService(),
        milvus_store=FakeMilvusStore(),
        web_search_service=RetryingWebSearchService(),
        web_fetch_service=RecordingWebFetchService(),
        browser_service=RecordingBrowserService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
    )

    queries = agent._build_web_search_queries(
        position={
            "department_name": "国家税务总局",
            "office_name": "第一税务分局",
            "job_title": "综合管理岗",
            "position_code": "2026-001",
        },
        history_summary={
            "record_count": 1,
            "latest_recruit_count": 2,
            "latest_interview_ratio": 45.0,
            "latest_interview_score": None,
        },
        scope={
            "analysis_goal": "岗位竞争证据补全",
            "year": 2026,
            "query": "国家税务总局 岗位分析",
        },
    )

    assert any(
        "进面分数" in query or "面试分数" in query or "进面名单" in query
        for query in queries
    )
    assert any("报录比" in query for query in queries)
