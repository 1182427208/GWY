from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from app.gwy.services.policy_rag_service import PolicyRagService


class DummyEmbeddingService:
    def embed_text(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.0, 0.0, 0.0]


class DummyRerankService:
    def rerank(
        self,
        query: str,
        documents: list[dict[str, object]],  # noqa: ARG002
        top_n: int = 5,  # noqa: ARG002
    ) -> list[dict[str, object]]:
        return []


class DummyChatService:
    def stream_chat_completion(
        self,
        messages: list[dict[str, object]],  # noqa: ARG002
        temperature: float = 0.2,  # noqa: ARG002
    ):
        yield {"type": "reasoning", "text": "think first"}
        yield {"type": "content", "text": "final answer"}


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
        return SimpleNamespace(id=session_id, title="test")

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
        user_id: UUID,  # noqa: ARG002
        title: str | None = None,
        summary: str | None = None,
        last_intent: str | None = None,
        active_topic: str | None = None,
        mentioned_docs: list[str] | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=session_id,
            title=title or "test",
            last_intent=last_intent,
            active_topic=active_topic,
            mentioned_docs=mentioned_docs or [],
            summary=summary,
            created_at=None,
        )


def test_generate_answer_streaming_ignores_reasoning_chunks() -> None:
    service = PolicyRagService(
        session_service=DummySessionService(),
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
    )

    answer = service._generate_answer_streaming(  # noqa: SLF001
        {
            "query": "test question",
            "citations": [
                {
                    "doc_title": "Doc",
                    "section": "Section",
                    "content": "Evidence",
                }
            ],
        }
    )

    assert answer == "final answer"
