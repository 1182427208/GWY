from __future__ import annotations

from uuid import UUID, uuid4

from app import crud
from app.models import User, UserCreate
from sqlmodel import delete, select

from app.core.config import settings
from app.gwy.models import (
    GwyPositionAnalysisSnapshot,
    GwyPositionAnalysisStep,
    GwyPositionAnalysisTask,
    GwyUserProfile,
)
from app.gwy.services.position_analysis_service import PositionAnalysisService


class FakePositionCatalogService:
    def analyze_positions(
        self,
        *,
        position_ids: list[UUID],
        query: str,
        profile: dict[str, object] | None = None,
        top_k: int = 10,
    ) -> dict[str, object]:
        return {
            "analysis": "selected positions analyzed",
            "summary": {
                "query": query,
                "candidate_count": len(position_ids),
                "filtered_count": len(position_ids),
                "recommendation_count": 1,
                "top_positions": [
                    {
                        "department_name": "北京市人社局",
                        "job_title": "综合管理岗",
                        "position_code": "BJ-001",
                        "score": 91,
                    }
                ],
            },
            "recommendations": [
                {
                    "position_id": str(position_ids[0]),
                    "department_name": "北京市人社局",
                    "office_name": "规划处",
                    "job_title": "综合管理岗",
                    "position_code": "BJ-001",
                    "work_location": "北京",
                    "education_requirement": "本科",
                    "degree_requirement": "学士",
                    "major_requirement": "计算机类",
                    "score": 91,
                    "risk_level": "low",
                    "need_manual_confirm": False,
                    "reasons": [{"type": "major_match", "text": "专业条件匹配"}],
                    "risks": [],
                }
            ],
            "selected_positions": [
                {
                    "id": str(position_ids[0]),
                    "department_name": "北京市人社局",
                    "job_title": "综合管理岗",
                    "position_code": "BJ-001",
                    "work_location": "北京",
                }
            ],
            "retrieval_trace": [
                {
                    "step": "position_analysis",
                    "selected_count": len(position_ids),
                    "exact_match_count": len(position_ids),
                }
            ],
        }


class RecordingPositionCatalogService(FakePositionCatalogService):
    def __init__(self) -> None:
        self.last_profile: dict[str, object] | None = None

    def analyze_positions(
        self,
        *,
        position_ids: list[UUID],
        query: str,
        profile: dict[str, object] | None = None,
        top_k: int = 10,
    ) -> dict[str, object]:
        self.last_profile = dict(profile or {})
        return super().analyze_positions(
            position_ids=position_ids,
            query=query,
            profile=profile,
            top_k=top_k,
        )

    def get_position_history(
        self,
        position: dict[str, object],
        *,
        limit: int = 5,
    ) -> dict[str, object]:
        _ = limit
        return {
            "match_basis": "department_code_job_title",
            "records": [],
            "summary": {
                "record_count": 0,
                "history_years": [],
                "recruit_count_trend": "unknown",
                "interview_ratio_trend": "unknown",
                "latest_recruit_count": None,
                "latest_interview_ratio": None,
            },
        }


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
        return [
            {
                "id": "policy-1",
                "content": "计算机类岗位优先参考政策公告",
                "score": 0.97,
                "doc_title": "政策公告",
                "source_file": "policy.pdf",
                "metadata": {"doc_type": "policy"},
            }
        ]


class FakeWebSearchService:
    def search(self, query: str, *, top_k: int | None = None) -> list[dict[str, object]]:
        _ = top_k
        return [
            {
                "title": "示例政策公告",
                "url": "https://example.com/policy",
                "snippet": f"{query} 官方公告",
                "source": "searxng",
            }
        ]


class FakeWebFetchService:
    def fetch(self, url: str) -> dict[str, object]:
        return {
            "url": url,
            "final_url": url,
            "title": "示例政策公告",
            "text": "简短正文",
            "content_type": "text/html",
            "status_code": 200,
            "source": "fetch",
            "retrieved_via": "fetch_mcp",
            "is_pdf": False,
        }


class FakeBrowserService:
    def read(self, url: str) -> dict[str, object]:
        return {
            "url": url,
            "title": "示例政策公告",
            "text": "这是浏览器补抓后的正文内容，长度足够用于验证浏览器回退逻辑。",
            "content_type": "text/html",
            "source": "playwright",
            "retrieved_via": "playwright_mcp:read",
        }


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
            "risk_items": [
                {
                    "risk_type": "manual_confirm",
                    "risk_level": "low",
                    "evidence": "政策公告",
                    "explanation": "未发现明显风险。",
                    "suggestion": "保持关注政策更新",
                    "need_manual_confirm": False,
                }
            ],
            "trace": [
                {
                    "step": "risk_intent_analysis",
                    "hypothesis_count": 1,
                }
            ],
        }


class FakeReportGeneratorAgent:
    def run(
        self,
        *,
        title: str,
        recommendations: list[dict[str, object]],
        risk_review: dict[str, object],
    ) -> dict[str, object]:
        return {
            "outline": ["概览", "推荐岗位", "风险提示", "下一步"],
            "report": (
                f"# {title}\n\n"
                "## 概览\n"
                "- 这是一个用于验证分析图链的报告。"
            ),
            "trace": [{"step": "plan", "outline_count": 4}],
        }


class FakeFeishuPushAgent:
    def run(
        self,
        *,
        report_kind: str,
        title: str,
        report_text: str,
        task_id: str | None = None,
        report_url: str | None = None,
        webhook_url: str | None = None,
    ) -> dict[str, object]:
        return {
            "status": "sent",
            "error_message": None,
            "response_json": {"code": 0, "msg": "ok"},
            "trace": [
                {"step": "plan", "status": "done"},
                {"step": "push", "status": "done"},
                {"step": "reflect", "status": "sent"},
            ],
        }


class ForbiddenPositionCatalogService:
    def analyze_positions(self, *args, **kwargs) -> dict[str, object]:
        raise AssertionError("position catalog should not be queried before clarification")


def _sample_snapshot() -> dict[str, object]:
    return {
        "title": "北京岗位分析快照",
        "source_sheet": "Sheet1",
        "filters_json": {"year": 2026, "major": "计算机类"},
        "snapshot_json": {
            "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
            "visible_columns": ["department_name", "job_title", "work_location"],
            "notes": "优先北京岗位",
        },
        "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
        "visible_columns": ["department_name", "job_title", "work_location"],
        "notes": "优先北京岗位",
    }


def _create_profile(
    *,
    user_id,
    major: str = "计算机类",
    education: str = "本科",
    degree: str = "学士",
    feishu_webhook_url: str | None = None,
) -> GwyUserProfile:
    return GwyUserProfile(
        user_id=user_id,
        major=major,
        education=education,
        degree=degree,
        political_status="中共党员",
        target_regions=["北京"],
        notes="希望优先考虑北京地区岗位",
        feishu_webhook_url=feishu_webhook_url,
    )


def _save_profile(db, profile: GwyUserProfile) -> None:
    db.exec(delete(GwyUserProfile).where(GwyUserProfile.user_id == profile.user_id))
    db.add(profile)


def test_position_analysis_service_creates_trace_report_and_persists_rows(db) -> None:
    snapshot_before = len(db.exec(select(GwyPositionAnalysisSnapshot)).all())
    task_before = len(db.exec(select(GwyPositionAnalysisTask)).all())
    step_before = len(db.exec(select(GwyPositionAnalysisStep)).all())

    user = crud.get_user_by_email(session=db, email=settings.EMAIL_TEST_USER)
    if user is None:
        user = crud.create_user(
            session=db,
            user_create=UserCreate(
                email=settings.EMAIL_TEST_USER,
                password="TestPass123!",
            ),
        )
    _save_profile(
        db,
        _create_profile(
            user_id=user.id,
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        ),
    )
    db.commit()

    catalog_service = RecordingPositionCatalogService()
    service = PositionAnalysisService(
        session=db,
        position_catalog_service=catalog_service,
        embedding_service=FakeEmbeddingService(),
        rerank_service=FakeRerankService(),
        milvus_store=FakeMilvusStore(),
        web_search_service=FakeWebSearchService(),
        web_fetch_service=FakeWebFetchService(),
        browser_service=FakeBrowserService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
        feishu_push_agent=FakeFeishuPushAgent(),
    )

    result = service.run(
        snapshot=_sample_snapshot(),
        user_id=user.id,
    )

    assert result["status"] == "completed"
    assert result["task"]["stage"] == "persist_result"
    assert [item["step"] for item in result["trace"][:3]] == [
        "load_snapshot",
        "normalize_snapshot",
        "build_analysis_scope",
    ]
    assert catalog_service.last_profile is not None
    assert catalog_service.last_profile["major"] == "计算机类"
    assert result["task"]["input_json"]["user_profile"]["major"] == "计算机类"
    assert result["report"].startswith("# 北京岗位分析报告")
    assert result["output_json"]["agent_journey"]
    assert result["output_json"]["analysis_strategy"]["strategy_name"] == "explore_then_verify"
    assert any(item["step"] == "plan_analysis_strategy" for item in result["trace"])
    assert any(item["step"] == "observe_research_gaps" for item in result["trace"])
    assert any(item["step"] == "decide_report_focus" for item in result["trace"])
    assert any(item["step"] == "policy_evidence_plan" for item in result["trace"])
    assert any(item["step"] == "web_verification_plan" for item in result["trace"])
    assert result["output_json"]["analysis_decision"]["focus_positions"]

    snapshot_rows = db.exec(select(GwyPositionAnalysisSnapshot)).all()
    task_rows = db.exec(select(GwyPositionAnalysisTask)).all()
    step_rows = db.exec(select(GwyPositionAnalysisStep)).all()

    assert len(snapshot_rows) == snapshot_before + 1
    assert len(task_rows) == task_before + 1
    assert len(step_rows) >= step_before + 3
    created_task = db.get(GwyPositionAnalysisTask, UUID(result["task"]["id"]))
    assert created_task is not None
    assert created_task.report_text == result["report"]
    assert created_task.trace_json[: len(result["trace"])] == result["trace"]
    assert result["feishu_push"]["status"] == "sent"
    assert created_task.output_json["feishu_push"]["status"] == "sent"
    assert created_task.trace_json[-1]["step"] == "feishu_push"


def test_position_analysis_service_asks_for_missing_info_before_full_report(db) -> None:
    snapshot_before = len(db.exec(select(GwyPositionAnalysisSnapshot)).all())
    task_before = len(db.exec(select(GwyPositionAnalysisTask)).all())
    step_before = len(db.exec(select(GwyPositionAnalysisStep)).all())

    service = PositionAnalysisService(
        session=db,
        position_catalog_service=ForbiddenPositionCatalogService(),
        embedding_service=FakeEmbeddingService(),
        rerank_service=FakeRerankService(),
        milvus_store=FakeMilvusStore(),
        web_search_service=FakeWebSearchService(),
        web_fetch_service=FakeWebFetchService(),
        browser_service=FakeBrowserService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
        feishu_push_agent=FakeFeishuPushAgent(),
    )

    snapshot = _sample_snapshot()
    snapshot["filters_json"] = {"year": 2026}
    snapshot["snapshot_json"] = {
        "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
        "visible_columns": ["department_name", "job_title", "work_location"],
        "notes": "",
    }
    snapshot["notes"] = ""

    result = service.run(
        snapshot=snapshot,
        user_id=uuid4(),
    )

    assert result["status"] == "needs_more_info"
    assert result["task"]["stage"] == "clarify_requirements"
    assert result["needs_more_info"] is True
    assert result["missing_fields"]
    assert result["clarifying_questions"]
    assert "追问" in result["report"]
    assert result["output_json"]["agent_journey"]

    snapshot_rows = db.exec(select(GwyPositionAnalysisSnapshot)).all()
    task_rows = db.exec(select(GwyPositionAnalysisTask)).all()
    step_rows = db.exec(select(GwyPositionAnalysisStep)).all()

    assert len(snapshot_rows) == snapshot_before + 1
    assert len(task_rows) == task_before + 1
    assert len(step_rows) >= step_before + 4
    created_task = db.get(GwyPositionAnalysisTask, UUID(result["task"]["id"]))
    assert created_task is not None
    assert created_task.status == "needs_more_info"
    assert created_task.output_json["needs_more_info"] is True
    assert created_task.output_json["clarifying_questions"]


def test_position_analysis_service_uses_profile_to_skip_clarification(db) -> None:
    user = crud.get_user_by_email(session=db, email=settings.EMAIL_TEST_USER)
    if user is None:
        user = crud.create_user(
            session=db,
            user_create=UserCreate(
                email=settings.EMAIL_TEST_USER,
                password="TestPass123!",
            ),
        )
    _save_profile(db, _create_profile(user_id=user.id))
    db.commit()

    catalog_service = RecordingPositionCatalogService()
    service = PositionAnalysisService(
        session=db,
        position_catalog_service=catalog_service,
        embedding_service=FakeEmbeddingService(),
        rerank_service=FakeRerankService(),
        milvus_store=FakeMilvusStore(),
        web_search_service=FakeWebSearchService(),
        web_fetch_service=FakeWebFetchService(),
        browser_service=FakeBrowserService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
        feishu_push_agent=FakeFeishuPushAgent(),
    )

    snapshot = {
        "title": "北京岗位分析快照",
        "source_sheet": "Sheet1",
        "filters_json": {},
        "snapshot_json": {
            "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
            "visible_columns": ["department_name", "job_title", "work_location"],
            "notes": "",
        },
        "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
        "visible_columns": ["department_name", "job_title", "work_location"],
        "notes": "",
    }

    result = service.run(
        snapshot=snapshot,
        user_id=user.id,
    )

    assert result["status"] == "completed"
    assert result["task"]["stage"] == "persist_result"
    assert result["needs_more_info"] is False
    assert result["missing_fields"] == []
    assert result["clarifying_questions"] == []
    assert catalog_service.last_profile is not None
    assert catalog_service.last_profile["major"] == "计算机类"
    assert catalog_service.last_profile["education"] == "本科"
    assert catalog_service.last_profile["degree"] == "学士"
