from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from pymilvus import MilvusClient

from app.core.config import settings

DEFAULT_VECTOR_FIELD = "embedding"
DEFAULT_SEARCH_PARAMS: dict[str, Any] = {"metric_type": "COSINE", "params": {}}
POLICY_DOCUMENT_COLLECTION_NAME = "gwy_policy_documents"
EXAM_GUIDE_COLLECTION_NAME = "gwy_exam_guides"
MAJOR_CATALOG_COLLECTION_NAME = "gwy_major_catalogs"


@dataclass(slots=True)
class MilvusSearchHit:
    id: int | str
    score: float
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "score": self.score, **self.payload}


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def embed(self, text: str) -> list[float]:
        url = self._embedding_url()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                url,
                headers=headers,
                json={"model": self._model, "input": text},
            )
            response.raise_for_status()
            data = response.json()

        embedding = data["data"][0]["embedding"]
        return [float(value) for value in embedding]

    def _embedding_url(self) -> str:
        if self._base_url.endswith("/v1"):
            return f"{self._base_url}/embeddings"
        return f"{self._base_url}/v1/embeddings"


class MilvusRetrievalService:
    def __init__(
        self,
        client: MilvusClient | None = None,
        embedder: OpenAICompatibleEmbeddingClient | None = None,
    ) -> None:
        self._client = client or self._build_client()
        self._embedder = embedder or self._build_embedder()

    def search_policy_documents_by_text(
        self,
        query_text: str,
        top_k: int = 5,
        filter_expr: str | None = None,
    ) -> list[MilvusSearchHit]:
        return self.search_by_text(
            settings.MILVUS_COLLECTION_POLICY_DOCUMENTS
            or POLICY_DOCUMENT_COLLECTION_NAME,
            query_text,
            top_k=top_k,
            filter_expr=filter_expr,
        )

    def search_exam_guides_by_text(
        self,
        query_text: str,
        top_k: int = 5,
        filter_expr: str | None = None,
    ) -> list[MilvusSearchHit]:
        return self.search_by_text(
            settings.MILVUS_COLLECTION_EXAM_GUIDES or EXAM_GUIDE_COLLECTION_NAME,
            query_text,
            top_k=top_k,
            filter_expr=filter_expr,
        )

    def search_major_catalogs_by_text(
        self,
        query_text: str,
        top_k: int = 5,
        filter_expr: str | None = None,
    ) -> list[MilvusSearchHit]:
        return self.search_by_text(
            settings.MILVUS_COLLECTION_MAJOR_CATALOGS or MAJOR_CATALOG_COLLECTION_NAME,
            query_text,
            top_k=top_k,
            filter_expr=filter_expr,
        )

    def search_by_text(
        self,
        collection_name: str,
        query_text: str,
        top_k: int = 5,
        filter_expr: str | None = None,
    ) -> list[MilvusSearchHit]:
        embedding = self._embed(query_text)
        return self.search_by_vector(
            collection_name=collection_name,
            query_vector=embedding,
            top_k=top_k,
            filter_expr=filter_expr,
        )

    def search_by_vector(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        top_k: int = 5,
        filter_expr: str | None = None,
        output_fields: Sequence[str] | None = None,
        vector_field: str = DEFAULT_VECTOR_FIELD,
    ) -> list[MilvusSearchHit]:
        search_results = self._client.search(
            collection_name=collection_name,
            data=[list(query_vector)],
            anns_field=vector_field,
            filter=filter_expr or "",
            limit=top_k,
            output_fields=list(output_fields) if output_fields else None,
            search_params=DEFAULT_SEARCH_PARAMS,
        )
        if not search_results:
            return []

        hits: list[MilvusSearchHit] = []
        for row in search_results[0]:
            entity = self._extract_entity(row)
            hit_id = row.get("id")
            score = float(row.get("distance", row.get("score", 0.0)))
            hits.append(MilvusSearchHit(id=hit_id, score=score, payload=entity))
        return hits

    def _embed(self, text: str) -> list[float]:
        if not self._embedder:
            raise RuntimeError(
                "MILVUS embedding client is not configured. "
                "Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL."
            )
        return self._embedder.embed(text)

    def _extract_entity(self, row: dict[str, Any]) -> dict[str, Any]:
        entity = dict(row.get("entity") or {})
        for key, value in row.items():
            if key not in {"id", "distance", "score", "entity"}:
                entity.setdefault(key, value)
        return entity

    def _build_client(self) -> MilvusClient:
        if not settings.MILVUS_URI:
            raise RuntimeError("MILVUS_URI is not configured.")
        client_kwargs: dict[str, Any] = {"uri": settings.MILVUS_URI}
        if settings.MILVUS_TOKEN:
            client_kwargs["token"] = settings.MILVUS_TOKEN
        return MilvusClient(**client_kwargs)

    def _build_embedder(self) -> OpenAICompatibleEmbeddingClient | None:
        if not (settings.LLM_BASE_URL and settings.LLM_MODEL):
            return None
        return OpenAICompatibleEmbeddingClient(
            base_url=str(settings.LLM_BASE_URL),
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
        )


@lru_cache(maxsize=1)
def get_milvus_retrieval_service() -> MilvusRetrievalService:
    return MilvusRetrievalService()
