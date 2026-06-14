from __future__ import annotations

from app.gwy.services.policy_rag_service import PolicyRagService


class DummyEmbeddingService:
    def embed_text(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.0, 0.0, 0.0]


class DummyRerankService:
    def rerank(
        self,
        query: str,
        documents: list[dict[str, object]],
        top_n: int = 5,
    ) -> list[dict[str, object]]:  # noqa: ARG002,E501
        for item in documents:
            item["rerank_score"] = 0.9
        return list(documents)[:top_n]


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
        return [
            {
                "id": "chunk-1",
                "content": "报名确认需要查看官方公告和资格条件",
                "score": 0.91,
                "metadata": {},
                "year": 2026,
                "exam_type": "national",
                "province": "全国",
                "doc_group": "policy_qa",
                "doc_type": "registration_confirmation",
                "doc_title": "报名确认说明",
                "section": "报名确认",
                "question": "报名确认何时开始",
                "source_file": "policy.pdf",
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 1,
                "asset_type": "text",
                "image_id": None,
                "image_path": None,
                "table_id": None,
                "row_id": None,
                "table_image_path": None,
                "bbox_list": None,
                "linked_image_ids": [],
                "linked_table_ids": [],
                "rerank_score": None,
            }
        ]


class DummySessionService:
    def get_memory_context(self, *_, **__) -> dict[str, object]:
        return {}


def test_policy_rag_service_lightweight_react_review_refines_sparse_citations() -> None:
    service = PolicyRagService(
        session_service=DummySessionService(),
        embedding_service=DummyEmbeddingService(),
        rerank_service=DummyRerankService(),
        chat_service=DummyChatService(),
        milvus_store=DummyMilvusStore(),
    )

    result = service._node_react_evidence_review(
        {
            "query": "报名确认什么时候开始？",
            "year": 2026,
            "citations": [{"content": "报名确认", "source_kind": "policy"}],
            "rerank_results": [],
            "retrieval_trace": [],
            "need_rag": True,
            "top_k": 5,
            "metadata_filter": None,
            "session_attachments": [],
            "doc_group": "policy_qa",
            "doc_type": "registration_confirmation",
        }
    )

    assert result["retrieval_trace"][-1]["step"] == "react_evidence_review"
    assert result["citations"]
    assert result["rerank_results"]
