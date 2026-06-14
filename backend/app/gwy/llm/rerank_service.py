from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.gwy.llm.siliconflow_client import SiliconFlowClient


class RerankService:
    def __init__(self, *, client: SiliconFlowClient | None = None) -> None:
        self.client = client or SiliconFlowClient()

    def rerank(
        self,
        query: str,
        documents: Sequence[dict[str, Any]],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        normalized_documents = [doc for doc in documents if doc.get("content")]
        if not normalized_documents:
            return []

        rerank_results = self.client.rerank(
            query=query,
            documents=[str(doc["content"]) for doc in normalized_documents],
            top_n=top_n,
        )
        if not rerank_results:
            return self._fallback(normalized_documents, top_n)

        indexed: dict[int, float] = {
            int(item["index"]): float(item["score"]) for item in rerank_results
        }
        enriched: list[dict[str, Any]] = []
        for index, document in enumerate(normalized_documents):
            if index in indexed:
                enriched.append(
                    {
                        **document,
                        "rerank_score": indexed[index],
                    }
                )
        enriched.sort(key=lambda item: item["rerank_score"], reverse=True)
        return enriched[:top_n]

    def _fallback(
        self, documents: Sequence[dict[str, Any]], top_n: int
    ) -> list[dict[str, Any]]:
        return [
            {**document, "rerank_score": float(document.get("score", 0.0))}
            for document in list(documents)[:top_n]
        ]
