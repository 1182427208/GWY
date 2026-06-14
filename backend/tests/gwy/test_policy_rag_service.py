from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from app.gwy.services.policy_rag_service import PolicyRagService
from app.gwy.prompts.policy_rag import (
    DIRECT_ANSWER_SYSTEM_PROMPT,
    POLICY_RAG_SYSTEM_PROMPT,
    POSITION_RECOMMENDATION_SYSTEM_PROMPT,
)
from app.gwy.skills.policy_rag_rules import route_intent


class DummyEmbeddingService:
    def embed_text(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.0, 0.0, 0.0]


class DummyRerankService:
    def rerank(self, query: str, documents: list[dict[str, object]], top_n: int = 5) -> list[dict[str, object]]:  # noqa: ARG002,E501
        return []


class DummyChatService:
    def chat_completion(self, messages: list[dict[str, object]], temperature: float = 0.2) -> str:  # noqa: ARG002,E501
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

    def append_message(
        self,
        *,
        session_id: UUID,
        role: str,
        content: str,
        intent: str | None = None,
        historical_reference: bool = False,
        citations: list[dict[str, object]] | None = None,
        retrieval_trace: list[dict[str, object]] | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=UUID(int=2 if role == "assistant" else 1),
            session_id=session_id,
            role=role,
            content=content,
            intent=intent,
            historical_reference=historical_reference,
            citations=citations or [],
            retrieval_trace=retrieval_trace or [],
            metadata_json=metadata_json or {},
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
        user_id: UUID,
        title: str | None = None,
        summary: str | None = None,
        last_intent: str | None = None,
        active_topic: str | None = None,
        mentioned_docs: list[str] | None = None,
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


def test_citation_guard_returns_clear_message() -> None:
    service = PolicyRagService(
        session_service=DummySessionService(),
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
    )

    result = service._node_answer({"citations": [], "retrieval_trace": []})

    assert result["answer"] == "当前知识库未找到明确依据。"
    assert result["retrieval_trace"][-1]["step"] == "citation_guard"
    assert result["retrieval_trace"][-1]["passed"] is False


def test_route_intent_routes_smalltalk_without_rag() -> None:
    routed = route_intent("你好")

    assert routed["intent"] == "general_chat"
    assert routed["need_rag"] is False


def test_route_intent_routes_general_help_without_rag() -> None:
    routed = route_intent("你能帮我什么")

    assert routed["intent"] == "general_chat"
    assert routed["need_rag"] is False


def test_route_intent_routes_policy_question_to_rag() -> None:
    routed = route_intent("这个岗位的年龄限制是什么？")

    assert routed["need_rag"] is True
    assert routed["doc_group"] == "policy_qa"


def test_route_intent_routes_position_recommendation() -> None:
    routed = route_intent("帮我推荐几个适合我的岗位")

    assert routed["intent"] == "position_recommendation"
    assert routed["need_rag"] is False


def test_route_intent_routes_position_recommendation_without_explicit_job_word() -> None:
    routed = route_intent("按我的专业和学历帮我分析哪些更适合")

    assert routed["intent"] == "position_recommendation"
    assert routed["need_rag"] is False


def test_route_intent_routes_profile_based_position_request() -> None:
    routed = route_intent("政治面貌是中共党员，无基层工作经验，北京，应届生")

    assert routed["intent"] == "position_recommendation"
    assert routed["need_rag"] is False


def test_finalize_chat_turn_keeps_serialized_user_message_dict() -> None:
    service = PolicyRagService(
        session_service=DummySessionService(),
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
    )

    user_message = {
        "id": "user-1",
        "session_id": "session-1",
        "role": "user",
        "content": "你好",
        "intent": None,
        "historical_reference": False,
        "citations": [],
        "retrieval_trace": [],
        "metadata_json": {},
        "created_at": None,
    }
    result = {
        "answer": "你好，我在。",
        "intent": "general_chat",
        "historical_reference": False,
        "citations": [],
        "retrieval_trace": [],
        "rewritten_queries": [],
        "metadata_filter": None,
        "rerank_results": [],
        "session_attachments": [],
    }

    payload = service.finalize_chat_turn(
        session_id=UUID(int=1),
        user_id=UUID(int=2),
        query="你好",
        user_message=user_message,
        result=result,
    )

    assert payload["user_message"] == user_message
    assert payload["assistant_message"]["role"] == "assistant"
    assert payload["session"]["title"]


def test_prompt_strings_include_required_sections() -> None:
    assert "只使用检索到的证据回答" in POLICY_RAG_SYSTEM_PROMPT
    assert "不要写成统一模板" in POLICY_RAG_SYSTEM_PROMPT
    assert "语气要像一个靠谱、耐心、会接话的助手" in POLICY_RAG_SYSTEM_PROMPT

    assert "直答约束" in DIRECT_ANSWER_SYSTEM_PROMPT
    assert "不要机械套" in DIRECT_ANSWER_SYSTEM_PROMPT
    assert "尽量用自然对话收尾" in DIRECT_ANSWER_SYSTEM_PROMPT
    assert "岗位推荐约束" in POSITION_RECOMMENDATION_SYSTEM_PROMPT
    assert "国考岗位规划顾问" in POSITION_RECOMMENDATION_SYSTEM_PROMPT
