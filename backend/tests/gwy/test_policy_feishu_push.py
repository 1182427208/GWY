from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from sqlmodel import select

from app.core.config import settings
from app.gwy.models import GwyUserProfile
from app.gwy.services.policy_rag_service import PolicyRagService
from app.models import User


class DummyEmbeddingService:
    def embed_text(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.0, 0.0, 0.0]


class DummyRerankService:
    def rerank(
        self,
        query: str,  # noqa: ARG002
        documents: list[dict[str, object]],  # noqa: ARG002
        top_n: int = 5,  # noqa: ARG002
    ) -> list[dict[str, object]]:
        return []


class DummyChatService:
    def chat_completion(
        self,
        messages: list[dict[str, object]],  # noqa: ARG002
        temperature: float = 0.2,  # noqa: ARG002
    ) -> str:
        return "unused"


class DummyMilvusStore:
    def search(
        self,
        query_vector: list[float],  # noqa: ARG002
        filter_expr: str | None,  # noqa: ARG002
        top_k: int = 10,  # noqa: ARG002
    ) -> list[dict[str, object]]:
        return []


class DummySessionService:
    def get_session(self, session_id: UUID, user_id: UUID) -> SimpleNamespace:  # noqa: ARG002
        return SimpleNamespace(id=session_id, title="新会话")

    def append_message(self, **kwargs: object) -> SimpleNamespace:  # noqa: ARG002
        role = str(kwargs.get("role") or "")
        session_id = kwargs.get("session_id")
        content = str(kwargs.get("content") or "")
        intent = kwargs.get("intent")
        historical_reference = bool(kwargs.get("historical_reference", False))
        citations = list(kwargs.get("citations") or [])
        retrieval_trace = list(kwargs.get("retrieval_trace") or [])
        metadata_json = dict(kwargs.get("metadata_json") or {})
        return SimpleNamespace(
            id=UUID(int=2 if role == "assistant" else 1),
            session_id=session_id,
            role=role,
            content=content,
            intent=intent,
            historical_reference=historical_reference,
            citations=citations,
            retrieval_trace=retrieval_trace,
            metadata_json=metadata_json,
            created_at=None,
        )

    def list_messages(self, session_id: UUID, user_id: UUID) -> list[SimpleNamespace]:  # noqa: ARG002
        return []

    def build_session_summary(self, messages: list[SimpleNamespace]) -> str:  # noqa: ARG002
        return "summary"

    def update_session_state(
        self,
        *,
        session_id: UUID,
        user_id: UUID,  # noqa: ARG002
        title: str | None = None,
        summary: str | None = None,  # noqa: ARG002
        last_intent: str | None = None,  # noqa: ARG002
        active_topic: str | None = None,  # noqa: ARG002
        mentioned_docs: list[str] | None = None,  # noqa: ARG002
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=session_id,
            title=title or "新会话",
            last_intent=last_intent,
            active_topic=active_topic,
            mentioned_docs=mentioned_docs or [],
            summary=summary,
            created_at=None,
        )

    def consume_attachments(self, session_id: UUID, user_id: UUID) -> None:  # noqa: ARG002
        return None


class StubPositionAgent:
    def run(
        self,
        *,
        query: str,  # noqa: ARG002
        user_id,  # noqa: ANN001
        session_id=None,  # noqa: ANN001
        year: int = 2026,  # noqa: ARG002
        exam_type: str = "national",  # noqa: ARG002
        top_k: int = 5,  # noqa: ARG002
        profile_override: dict[str, object] | None = None,  # noqa: ARG002
    ) -> dict[str, object]:
        return {
            "answer": "已进入岗位推荐",
            "recommendations": [
                {
                    "department_name": "北京市人社局",
                    "job_title": "综合管理岗",
                    "score": 91,
                    "risk_level": "low",
                }
            ],
            "retrieval_trace": [{"step": "position_recommendation"}],
            "need_more_info": False,
            "missing_fields": [],
            "task_id": None,
        }


class FakeRiskReviewAgent:
    def run(
        self,
        *,
        query: str,  # noqa: ARG002
        recommendations: list[dict[str, object]],  # noqa: ARG002
    ) -> dict[str, object]:
        return {
            "risk_level": "low",
            "need_manual_confirm": False,
            "risk_items": [],
            "trace": [{"step": "risk_review"}],
        }


class FakeReportGeneratorAgent:
    def run(
        self,
        *,
        title: str,
        recommendations: list[dict[str, object]],  # noqa: ARG002
        risk_review: dict[str, object],  # noqa: ARG002
    ) -> dict[str, object]:
        return {
            "outline": ["概览"],
            "report": f"# {title}\n\n## 概览\n- 已生成推荐报告",
            "trace": [{"step": "plan"}],
        }


class FakeFeishuPushAgent:
    def run(
        self,
        *,
        report_kind: str,  # noqa: ARG002
        title: str,  # noqa: ARG002
        report_text: str,  # noqa: ARG002
        task_id: str | None = None,  # noqa: ARG002
        report_url: str | None = None,  # noqa: ARG002
        webhook_url: str | None = None,  # noqa: ARG002
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


def test_position_recommendation_pushes_report_to_feishu(db) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        GwyUserProfile(
            user_id=user.id,
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        )
    )
    db.commit()

    service = PolicyRagService(
        session=db,
        session_service=DummySessionService(),
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
        feishu_push_agent=FakeFeishuPushAgent(),
    )
    service.position_agent = StubPositionAgent()
    service.risk_review_agent = FakeRiskReviewAgent()
    service.report_generator_agent = FakeReportGeneratorAgent()

    result = service._node_position_recommendation(
        {
            "query": "请帮我推荐岗位",
            "user_id": str(user.id),
            "session_id": None,
            "year": 2026,
            "exam_type": "national",
            "top_k": 5,
            "position_profile": None,
            "retrieval_trace": [],
        }
    )

    assert result["decision_branch"] == "postgresql_position_recommendation"
    assert result["feishu_push"]["status"] == "sent"
    assert result["retrieval_trace"][-1]["step"] == "feishu_push"
