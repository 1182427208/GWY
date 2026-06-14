from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pymilvus import DataType, MilvusClient

from app.core.config import settings

OFFICIAL_POLICY_COLLECTION_NAME = settings.MILVUS_COLLECTION_POLICY_RAG


def _normalize_collection_suffix(value: UUID | str) -> str:
    if isinstance(value, UUID):
        return value.hex
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", str(value).strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "anonymous"


def build_policy_collection_name(owner_user_id: UUID | str | None = None) -> str:
    if owner_user_id is None:
        return OFFICIAL_POLICY_COLLECTION_NAME
    return f"{OFFICIAL_POLICY_COLLECTION_NAME}_user_{_normalize_collection_suffix(owner_user_id)}"


class MilvusPolicyStore:
    def __init__(
        self,
        *,
        client: MilvusClient | None = None,
        collection_name: str | None = None,
        owner_user_id: UUID | str | None = None,
        embedding_dim: int | None = None,
    ) -> None:
        self.owner_user_id = owner_user_id
        self.collection_name = collection_name or build_policy_collection_name(
            owner_user_id
        )
        self.embedding_dim = embedding_dim or settings.EMBEDDING_DIM
        self._client: MilvusClient | None = None
        self._init_error: Exception | None = None
        try:
            self._client = client or self._build_client()
        except Exception as exc:  # pragma: no cover - best-effort fallback
            self._init_error = exc
            self._client = None

    @classmethod
    def official_collection_name(cls) -> str:
        return OFFICIAL_POLICY_COLLECTION_NAME

    @classmethod
    def user_collection_name(cls, user_id: UUID | str) -> str:
        return build_policy_collection_name(user_id)

    def create_collection_if_not_exists(self) -> bool:
        if self._client is None:
            return False
        if self._client.has_collection(self.collection_name):
            return False

        schema = self._client.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
        )
        schema.add_field(
            field_name="id",
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=64,
        )
        schema.add_field(
            field_name="vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=self.embedding_dim,
        )
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=16384,
        )
        schema.add_field(field_name="year", datatype=DataType.INT64)
        schema.add_field(
            field_name="exam_type",
            datatype=DataType.VARCHAR,
            max_length=64,
        )
        schema.add_field(
            field_name="province",
            datatype=DataType.VARCHAR,
            max_length=64,
        )
        schema.add_field(
            field_name="doc_group",
            datatype=DataType.VARCHAR,
            max_length=64,
        )
        schema.add_field(
            field_name="doc_type",
            datatype=DataType.VARCHAR,
            max_length=64,
        )
        schema.add_field(
            field_name="doc_title",
            datatype=DataType.VARCHAR,
            max_length=255,
        )
        schema.add_field(
            field_name="section",
            datatype=DataType.VARCHAR,
            max_length=255,
        )
        schema.add_field(
            field_name="question",
            datatype=DataType.VARCHAR,
            max_length=1024,
        )
        schema.add_field(
            field_name="source_file",
            datatype=DataType.VARCHAR,
            max_length=512,
        )
        schema.add_field(field_name="page_start", datatype=DataType.INT64)
        schema.add_field(field_name="page_end", datatype=DataType.INT64)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(
            field_name="metadata_json",
            datatype=DataType.VARCHAR,
            max_length=16384,
        )
        schema.add_field(
            field_name="asset_type",
            datatype=DataType.VARCHAR,
            max_length=32,
        )
        schema.add_field(
            field_name="image_id",
            datatype=DataType.VARCHAR,
            max_length=64,
        )
        schema.add_field(
            field_name="image_path",
            datatype=DataType.VARCHAR,
            max_length=1024,
        )
        schema.add_field(
            field_name="table_id",
            datatype=DataType.VARCHAR,
            max_length=64,
        )
        schema.add_field(
            field_name="row_id",
            datatype=DataType.VARCHAR,
            max_length=64,
        )
        schema.add_field(
            field_name="table_image_path",
            datatype=DataType.VARCHAR,
            max_length=1024,
        )
        schema.add_field(
            field_name="bbox_list",
            datatype=DataType.VARCHAR,
            max_length=8192,
        )
        schema.add_field(
            field_name="linked_image_ids",
            datatype=DataType.VARCHAR,
            max_length=2048,
        )
        schema.add_field(
            field_name="linked_table_ids",
            datatype=DataType.VARCHAR,
            max_length=2048,
        )
        schema.add_field(
            field_name="created_at",
            datatype=DataType.VARCHAR,
            max_length=64,
        )

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )
        return True

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> list[str]:
        if not chunks:
            return []
        if self._client is None:
            return []
        self.create_collection_if_not_exists()

        rows: list[dict[str, Any]] = []
        ids: list[str] = []
        for chunk in chunks:
            vector = [float(value) for value in chunk.get("vector", [])]
            self._validate_vector(vector)
            metadata = dict(chunk.get("metadata") or {})
            metadata.setdefault("chunk_type", str(chunk.get("chunk_type", "")))
            metadata.setdefault("asset_type", str(chunk.get("asset_type", "text")))
            if chunk.get("image_id"):
                metadata.setdefault("image_id", str(chunk.get("image_id")))
            if chunk.get("image_path"):
                metadata.setdefault("image_path", str(chunk.get("image_path")))
            if chunk.get("table_id"):
                metadata.setdefault("table_id", str(chunk.get("table_id")))
            if chunk.get("row_id"):
                metadata.setdefault("row_id", str(chunk.get("row_id")))
            if chunk.get("table_image_path"):
                metadata.setdefault("table_image_path", str(chunk.get("table_image_path")))
            metadata.setdefault("bbox_list", list(chunk.get("bbox_list") or []))
            metadata.setdefault("linked_image_ids", list(chunk.get("linked_image_ids") or []))
            metadata.setdefault("linked_table_ids", list(chunk.get("linked_table_ids") or []))
            chunk_id = str(chunk.get("chunk_id") or metadata.get("chunk_id") or "")
            if not chunk_id:
                raise ValueError("Chunk is missing chunk_id.")
            row = {
                "id": self._truncate_text(chunk_id, 64),
                "vector": vector,
                "content": self._truncate_text(str(chunk.get("content", "")), 16384),
                "year": int(metadata.get("year", 0)),
                "exam_type": self._truncate_text(
                    str(metadata.get("exam_type", "")), 64
                ),
                "province": self._truncate_text(
                    str(metadata.get("province", "")), 64
                ),
                "doc_group": self._truncate_text(
                    str(metadata.get("doc_group", "")), 64
                ),
                "doc_type": self._truncate_text(
                    str(metadata.get("doc_type", "")), 64
                ),
                "doc_title": self._truncate_text(
                    str(metadata.get("doc_title", "")), 255
                ),
                "section": self._truncate_text(str(chunk.get("section", "")), 255),
                "question": self._truncate_text(
                    str(chunk.get("question", "")), 1024
                ),
                "source_file": self._truncate_text(
                    str(metadata.get("source_file", "")), 512
                ),
                "page_start": int(chunk.get("page_start", 0)),
                "page_end": int(chunk.get("page_end", 0)),
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "metadata_json": self._truncate_text(
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    16384,
                ),
                "asset_type": self._truncate_text(
                    str(chunk.get("asset_type") or metadata.get("asset_type", "text")),
                    32,
                ),
                "image_id": self._truncate_text(
                    str(chunk.get("image_id") or metadata.get("image_id", "")),
                    64,
                ),
                "image_path": self._truncate_text(
                    str(chunk.get("image_path") or metadata.get("image_path", "")),
                    1024,
                ),
                "table_id": self._truncate_text(
                    str(chunk.get("table_id") or metadata.get("table_id", "")),
                    64,
                ),
                "row_id": self._truncate_text(
                    str(chunk.get("row_id") or metadata.get("row_id", "")),
                    64,
                ),
                "table_image_path": self._truncate_text(
                    str(chunk.get("table_image_path") or metadata.get("table_image_path", "")),
                    1024,
                ),
                "bbox_list": self._truncate_text(
                    json.dumps(chunk.get("bbox_list") or metadata.get("bbox_list") or [], ensure_ascii=False),
                    8192,
                ),
                "linked_image_ids": self._truncate_text(
                    json.dumps(
                        chunk.get("linked_image_ids") or metadata.get("linked_image_ids") or [],
                        ensure_ascii=False,
                    ),
                    2048,
                ),
                "linked_table_ids": self._truncate_text(
                    json.dumps(
                        chunk.get("linked_table_ids") or metadata.get("linked_table_ids") or [],
                        ensure_ascii=False,
                    ),
                    2048,
                ),
                "created_at": self._truncate_text(
                    datetime.now(timezone.utc).isoformat(),
                    64,
                ),
            }
            rows.append(row)
            ids.append(chunk_id)

        self._client.insert(collection_name=self.collection_name, data=rows)
        return ids

    def search(
        self,
        query_vector: list[float],
        filter_expr: str | None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if self._client is None:
            return []
        self.create_collection_if_not_exists()
        self._validate_vector(query_vector)

        search_results = self._client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            anns_field="vector",
            limit=top_k,
            filter=filter_expr,
            output_fields=[
                "content",
                "year",
                "exam_type",
                "province",
                "doc_group",
                "doc_type",
                "doc_title",
                "section",
                "question",
                "source_file",
                "page_start",
                "page_end",
                "chunk_index",
                "metadata_json",
                "asset_type",
                "image_id",
                "image_path",
                "table_id",
                "row_id",
                "table_image_path",
                "bbox_list",
                "linked_image_ids",
                "linked_table_ids",
                "created_at",
            ],
            search_params={"metric_type": "COSINE", "params": {}},
        )
        if not search_results:
            return []

        hits: list[dict[str, Any]] = []
        for row in search_results[0]:
            entity = dict(row.get("entity") or {})
            score = float(row.get("distance", row.get("score", 0.0)))
            metadata = self._decode_metadata(entity.get("metadata_json"))
            hits.append(
                {
                    "id": str(row.get("id", "")),
                    "content": str(entity.get("content", "")),
                    "score": score,
                    "metadata": metadata,
                    "year": entity.get("year"),
                    "exam_type": entity.get("exam_type"),
                    "province": entity.get("province"),
                    "doc_group": entity.get("doc_group"),
                    "doc_type": entity.get("doc_type"),
                    "doc_title": entity.get("doc_title"),
                    "section": entity.get("section"),
                    "question": entity.get("question"),
                    "source_file": entity.get("source_file"),
                    "page_start": entity.get("page_start"),
                    "page_end": entity.get("page_end"),
                    "chunk_index": entity.get("chunk_index"),
                    "asset_type": entity.get("asset_type"),
                    "image_id": entity.get("image_id"),
                    "image_path": entity.get("image_path"),
                    "table_id": entity.get("table_id"),
                    "row_id": entity.get("row_id"),
                    "table_image_path": entity.get("table_image_path"),
                    "bbox_list": entity.get("bbox_list"),
                    "linked_image_ids": entity.get("linked_image_ids"),
                    "linked_table_ids": entity.get("linked_table_ids"),
                    "rerank_score": None,
                }
            )
        return hits

    def query_documents(
        self,
        filter_expr: str | None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if self._client is None:
            return []
        self.create_collection_if_not_exists()
        query_filter = filter_expr or 'id != ""'
        rows = self._client.query(
            collection_name=self.collection_name,
            filter=query_filter,
            output_fields=[
                "id",
                "content",
                "year",
                "exam_type",
                "province",
                "doc_group",
                "doc_type",
                "doc_title",
                "section",
                "question",
                "source_file",
                "page_start",
                "page_end",
                "chunk_index",
                "metadata_json",
                "asset_type",
                "image_id",
                "image_path",
                "table_id",
                "row_id",
                "table_image_path",
                "bbox_list",
                "linked_image_ids",
                "linked_table_ids",
                "created_at",
            ],
            limit=limit,
        )
        results: list[dict[str, Any]] = []
        for row in rows or []:
            entity = dict(row)
            results.append(
                {
                    "id": str(entity.get("id", "")),
                    "content": str(entity.get("content", "")),
                    "score": 0.0,
                    "metadata": self._decode_metadata(entity.get("metadata_json")),
                    "year": entity.get("year"),
                    "exam_type": entity.get("exam_type"),
                    "province": entity.get("province"),
                    "doc_group": entity.get("doc_group"),
                    "doc_type": entity.get("doc_type"),
                    "doc_title": entity.get("doc_title"),
                    "section": entity.get("section"),
                    "question": entity.get("question"),
                    "source_file": entity.get("source_file"),
                    "page_start": entity.get("page_start"),
                    "page_end": entity.get("page_end"),
                    "chunk_index": entity.get("chunk_index"),
                    "asset_type": entity.get("asset_type"),
                    "image_id": entity.get("image_id"),
                    "image_path": entity.get("image_path"),
                    "table_id": entity.get("table_id"),
                    "row_id": entity.get("row_id"),
                    "table_image_path": entity.get("table_image_path"),
                    "bbox_list": entity.get("bbox_list"),
                    "linked_image_ids": entity.get("linked_image_ids"),
                    "linked_table_ids": entity.get("linked_table_ids"),
                    "rerank_score": None,
                }
            )
        return results

    def drop_collection(self) -> bool:
        if self._client is None:
            return False
        if not self._client.has_collection(self.collection_name):
            return False
        self._client.drop_collection(self.collection_name)
        return True

    def delete_chunks_by_ids(self, chunk_ids: list[str]) -> int:
        if self._client is None or not chunk_ids:
            return 0
        self.create_collection_if_not_exists()
        normalized_ids = [str(chunk_id).strip() for chunk_id in chunk_ids if str(chunk_id).strip()]
        if not normalized_ids:
            return 0
        result = self._client.delete(
            collection_name=self.collection_name,
            ids=normalized_ids,
        )
        deleted_count = int(result.get("delete_count", len(normalized_ids)))
        return deleted_count

    def delete_by_filter(self, filter_expr: str) -> int:
        if self._client is None:
            return 0
        self.create_collection_if_not_exists()
        result = self._client.delete(
            collection_name=self.collection_name,
            filter=filter_expr,
        )
        return int(result.get("delete_count", 0))

    def reset_collection(self) -> bool:
        dropped = self.drop_collection()
        self.create_collection_if_not_exists()
        return dropped

    def _build_client(self) -> MilvusClient:
        if not settings.MILVUS_URI:
            raise RuntimeError("MILVUS_URI is not configured.")
        uri = settings.MILVUS_URI
        if not uri.startswith(("http://", "https://")):
            uri = f"http://{uri}"
        client_kwargs: dict[str, Any] = {"uri": uri}
        if settings.MILVUS_TOKEN:
            client_kwargs["token"] = settings.MILVUS_TOKEN
        client = MilvusClient(**client_kwargs)

        db_name = settings.MILVUS_DB_NAME.strip() if settings.MILVUS_DB_NAME else ""
        if not db_name:
            return client

        try:
            available_databases = client.list_databases()
        except Exception as exc:  # pragma: no cover - defensive bootstrap
            raise RuntimeError("Failed to inspect Milvus databases.") from exc

        if db_name not in available_databases:
            client.create_database(db_name)
        client.use_database(db_name)
        return client

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.embedding_dim:
            raise ValueError(
                f"Vector dimension mismatch: expected {self.embedding_dim}, got {len(vector)}."
            )

    def _decode_metadata(self, raw_metadata: Any) -> dict[str, Any]:
        if isinstance(raw_metadata, dict):
            return raw_metadata
        if isinstance(raw_metadata, str) and raw_metadata:
            try:
                return json.loads(raw_metadata)
            except json.JSONDecodeError:
                return {}
        return {}

    def _truncate_text(self, value: str, max_length: int) -> str:
        if len(value.encode("utf-8")) <= max_length:
            return value
        encoded = value.encode("utf-8")[:max_length]
        while encoded:
            try:
                return encoded.decode("utf-8")
            except UnicodeDecodeError as exc:
                encoded = encoded[: exc.start]
        return ""
