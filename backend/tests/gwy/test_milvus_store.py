from __future__ import annotations

import json
from uuid import UUID

from app.core.config import settings
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


class FakeSchema:
    def __init__(self) -> None:
        self.fields: list[dict[str, object]] = []

    def add_field(self, **kwargs: object) -> None:
        self.fields.append(kwargs)


class FakeIndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict[str, object]] = []

    def add_index(self, **kwargs: object) -> None:
        self.indexes.append(kwargs)


class FakeMilvusClient:
    def __init__(self, expected_collection_name: str = "gwy_policy_chunks") -> None:
        self.collection_exists = False
        self.created_collection: dict[str, object] | None = None
        self.inserted_rows: list[dict[str, object]] = []
        self.deleted_requests: list[dict[str, object]] = []
        self.expected_collection_name = expected_collection_name

    def has_collection(self, collection_name: str) -> bool:  # noqa: ARG002
        return self.collection_exists

    def create_schema(self, **kwargs: object) -> FakeSchema:
        self.schema_kwargs = kwargs
        return FakeSchema()

    def prepare_index_params(self) -> FakeIndexParams:
        return FakeIndexParams()

    def create_collection(
        self,
        *,
        collection_name: str,
        schema: FakeSchema,
        index_params: FakeIndexParams,
    ) -> None:
        self.created_collection = {
            "collection_name": collection_name,
            "schema": schema,
            "index_params": index_params,
        }
        self.collection_exists = True

    def insert(self, *, collection_name: str, data: list[dict[str, object]]) -> None:
        assert collection_name == self.expected_collection_name
        self.inserted_rows.extend(data)

    def search(
        self,
        *,
        collection_name: str,
        data: list[list[float]],  # noqa: ARG002
        anns_field: str,  # noqa: ARG002
        limit: int,  # noqa: ARG002
        filter: str | None,  # noqa: A002
        output_fields: list[str],  # noqa: ARG002
        search_params: dict[str, object],  # noqa: ARG002
    ) -> list[list[dict[str, object]]]:
        assert collection_name == self.expected_collection_name
        return [
            [
                {
                    "id": "chunk-1",
                    "distance": 0.93,
                    "entity": {
                        "content": "Admit ticket print guidance",
                        "metadata_json": json.dumps({"year": 2026}),
                    },
                }
            ]
        ]

    def delete(
        self,
        *,
        collection_name: str,
        ids: list[str] | str | int | None = None,
        timeout: float | None = None,  # noqa: ARG002
        filter: str | None = None,  # noqa: A002
        partition_name: str | None = None,  # noqa: ARG002
        **kwargs: object,  # noqa: ARG002
    ) -> dict[str, int]:
        assert collection_name == self.expected_collection_name
        self.deleted_requests.append(
            {
                "ids": ids,
                "filter": filter,
            }
        )
        if isinstance(ids, list):
            return {"delete_count": len(ids)}
        return {"delete_count": 1}


def test_milvus_store_creates_and_inserts_chunks() -> None:
    client = FakeMilvusClient()
    store = MilvusPolicyStore(
        client=client,
        collection_name="gwy_policy_chunks",
        embedding_dim=3,
    )

    store.create_collection_if_not_exists()
    ids = store.insert_chunks(
        [
            {
                "chunk_id": "chunk-1",
                "content": "Admit ticket print guidance",
                "question": "How do I print the admission ticket?",
                "section": "Admission ticket",
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 0,
                "metadata": {
                    "year": 2026,
                    "exam_type": "national",
                    "province": "national",
                    "doc_group": "exam_affairs_qa",
                    "doc_type": "admission_ticket",
                    "doc_title": "How to print the admission ticket",
                    "source_file": "data/exam_affairs_qa/how_to_print_ticket.pdf",
                },
                "vector": [0.1, 0.2, 0.3],
            }
        ]
    )

    assert ids == ["chunk-1"]
    assert client.created_collection is not None
    assert client.inserted_rows[0]["content"] == "Admit ticket print guidance"
    assert client.inserted_rows[0]["metadata_json"]

    results = store.search(
        [0.1, 0.2, 0.3], filter_expr='doc_group == "exam_affairs_qa"'
    )
    assert results[0]["content"] == "Admit ticket print guidance"
    assert results[0]["metadata"]["year"] == 2026


def test_milvus_store_uses_user_isolated_collection() -> None:
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    expected_collection = (
        f"{settings.MILVUS_COLLECTION_POLICY_RAG}_user_{user_id.hex}"
    )
    client = FakeMilvusClient(expected_collection_name=expected_collection)
    store = MilvusPolicyStore(
        client=client,
        owner_user_id=user_id,
        embedding_dim=3,
    )

    assert store.collection_name == expected_collection

    ids = store.insert_chunks(
        [
            {
                "chunk_id": "chunk-user-1",
                "content": "User upload policy note",
                "question": "How do I upload files?",
                "section": "Upload",
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 0,
                "metadata": {
                    "year": 2026,
                    "exam_type": "national",
                    "province": "national",
                    "doc_group": "policy_qa",
                    "doc_type": "other_policy",
                    "doc_title": "User upload policy note",
                    "source_file": "data/user_uploads/note.pdf",
                },
                "vector": [0.1, 0.2, 0.3],
            }
        ]
    )

    assert ids == ["chunk-user-1"]
    assert client.inserted_rows[0]["source_file"] == "data/user_uploads/note.pdf"


def test_milvus_store_can_delete_chunks_by_ids() -> None:
    client = FakeMilvusClient()
    store = MilvusPolicyStore(
        client=client,
        collection_name="gwy_policy_chunks",
        embedding_dim=3,
    )

    deleted = store.delete_chunks_by_ids(["chunk-1", "chunk-2"])

    assert deleted == 2
    assert client.deleted_requests[0]["ids"] == ["chunk-1", "chunk-2"]
