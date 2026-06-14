from __future__ import annotations

from types import SimpleNamespace

from sqlmodel import Session

from app.gwy.services.policy_rag_service import PolicyRagService
from app.gwy.skills.position_recommendation_skills import (
    PositionRecommendationCriteria,
)


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


class StubPositionAgent:
    def __init__(self) -> None:
        self.received_profile: dict[str, object] | None = None

    def run(
        self,
        *,
        query: str,  # noqa: ARG002
        user_id,  # noqa: ANN001
        session_id=None,  # noqa: ANN001
        year: int = 2026,  # noqa: ARG002
        exam_type: str = "national",  # noqa: ARG002
        top_k: int = 5,  # noqa: ARG002
        profile_override: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.received_profile = profile_override
        return {
            "answer": "已进入岗位推荐",
            "recommendations": [],
            "retrieval_trace": [{"step": "position_recommendation"}],
            "need_more_info": False,
            "missing_fields": [],
            "task_id": None,
        }


def test_explicit_position_mode_bypasses_rag_router(db: Session) -> None:
    service = PolicyRagService(
        session=db,
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
    )

    routed = service._node_route_intent(
        {
            "query": "请按我填写的条件推荐岗位",
            "mode": "position_recommendation",
            "intent_hint": "position_recommendation",
            "retrieval_trace": [],
        }
    )

    assert routed["intent"] == "position_recommendation"
    assert routed["need_rag"] is False
    assert routed["doc_group"] == "position_table"
    assert routed["doc_type"] == "position_recommendation"


def test_position_profile_override_is_forwarded_to_agent(db: Session) -> None:
    service = PolicyRagService(
        session=db,
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
    )
    agent = StubPositionAgent()
    service.position_agent = agent

    result = service._node_position_recommendation(
        {
            "query": "请按结构化条件推荐岗位",
            "user_id": None,
            "session_id": None,
            "year": 2026,
            "exam_type": "national",
            "top_k": 5,
            "position_profile": {
                "major": "法学",
                "education": "本科",
                "degree": "学士",
                "political_status": "中共党员",
            },
            "retrieval_trace": [],
        }
    )

    assert agent.received_profile == {
        "major": "法学",
        "education": "本科",
        "degree": "学士",
        "political_status": "中共党员",
    }
    assert result["decision_branch"] == "postgresql_position_recommendation"
    assert result["need_more_info"] is False


def test_explicit_position_mode_does_not_fallback_to_unfiltered_candidates(
    db: Session,
) -> None:
    service = PolicyRagService(
        session=db,
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
    )

    state = {
        "query": "请按结构化条件进行岗位匹配",
        "year": 2026,
        "exam_type": "national",
        "mode": "position_recommendation",
        "retrieval_trace": [],
        "criteria": PositionRecommendationCriteria(
            query="请按结构化条件进行岗位匹配",
            major="不存在的专业",
            education="本科",
            degree="学士",
            political_status="中共党员",
            target_regions=["北京"],
        ),
    }

    result = service.position_agent._node_load_candidates(state)  # type: ignore[union-attr]

    assert result["candidates"] == []
    trace = result["retrieval_trace"][-1]
    assert trace["year_filter_fallback"] is False
    assert trace["sql_filtered"] is True
