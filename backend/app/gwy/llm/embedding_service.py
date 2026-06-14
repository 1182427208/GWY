from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core.config import settings
from app.gwy.llm.siliconflow_client import SiliconFlowClient


class EmbeddingService:
    def __init__(
        self,
        *,
        client: SiliconFlowClient | None = None,
        embedding_dim: int | None = None,
    ) -> None:
        self.client = client or SiliconFlowClient()
        self.embedding_dim = embedding_dim or settings.EMBEDDING_DIM

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = [text.strip() for text in texts if text and text.strip()]
        if not normalized:
            raise ValueError("Embedding input cannot be empty.")
        if len(normalized) != len(texts):
            raise ValueError("Embedding input contains empty text.")

        vectors = self.client.embeddings(
            normalized,
            dimensions=self.embedding_dim,
        )
        self._validate_dimensions(vectors)
        return vectors

    def _validate_dimensions(self, vectors: Sequence[Sequence[Any]]) -> None:
        for vector in vectors:
            if len(vector) != self.embedding_dim:
                raise ValueError(
                    "Embedding dimension mismatch: "
                    f"expected {self.embedding_dim}, got {len(vector)}."
                )
