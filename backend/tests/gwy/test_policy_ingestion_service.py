from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.gwy.services.chunk_debug_service import ChunkDebugService
from app.gwy.services.policy_ingestion_service import PolicyIngestionService
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


class FakeEmbeddingService:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeMilvusStore:
    def __init__(self, collection_name: str | None = None) -> None:
        self.created = False
        self.inserted: list[dict[str, object]] = []
        self.collection_name = (
            collection_name or MilvusPolicyStore.official_collection_name()
        )

    def create_collection_if_not_exists(self) -> bool:
        self.created = True
        return True

    def insert_chunks(self, chunks: list[dict[str, object]]) -> list[str]:
        self.inserted.extend(chunks)
        return [str(chunk["chunk_id"]) for chunk in chunks]


@dataclass
class FakeResult:
    value: object | None = None

    def first(self) -> object | None:
        return self.value


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def get(self, model: object, key: object) -> object | None:  # noqa: ARG002
        return None

    def exec(self, statement: object) -> FakeResult:  # noqa: ARG002
        return FakeResult()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True


def test_policy_ingestion_service_ingests_mock_pdf(
    monkeypatch,
    tmp_path,
) -> None:
    from app.gwy.services import policy_ingestion_service as ingestion_module

    monkeypatch.setattr(
        ingestion_module,
        "load_pdf_pages",
        lambda file_path: [
            {
                "page": 1,
                "text": "Question: How do I print the admission ticket?\n"
                "Answer: Log in to the system and print it during the allowed window.",
            }
        ],
    )
    monkeypatch.setattr(
        ingestion_module,
        "analyze_pdf_layout",
        lambda file_path: {"pages": [{"page": 1, "blocks": []}]},
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_image_assets",
        lambda file_path, layout_pages=None: [],
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_tables",
        lambda file_path, layout_pages=None: {"tables": [], "rows": [], "chunks": []},
    )

    session = FakeSession()
    store = FakeMilvusStore()
    debug_service = ChunkDebugService(
        debug_root=tmp_path / "chunks_debug",
        preview_root=tmp_path / "chunks_preview",
    )
    service = PolicyIngestionService(
        session=session,
        embedding_service=FakeEmbeddingService(),
        chunk_debug_service=debug_service,
        milvus_store=store,
    )

    result = service.ingest_policy_pdf(
        "data/exam_affairs_qa/how_to_print_ticket.pdf"
    )

    assert result["success"] is True
    assert result["chunk_count"] == 1
    assert result["chunk_stats"]["total_chunks"] == 1
    assert result["warnings"] == []
    assert (tmp_path / "chunks_debug").exists()
    assert len(list((tmp_path / "chunks_debug").glob("*.chunks.jsonl"))) == 1
    assert len(list((tmp_path / "chunks_debug").glob("*.chunks.csv"))) == 1
    assert len(list((tmp_path / "chunks_preview").glob("*.preview.html"))) == 1
    assert store.created is True
    assert len(store.inserted) == 1
    assert session.committed is True
    assert len(session.added) >= 1
    assert any(
        getattr(item, "embedding_status", None) == "completed" for item in session.added
    )


def test_policy_ingestion_service_records_user_collection_name(
    monkeypatch,
    tmp_path,
) -> None:
    session = FakeSession()
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    expected_collection = MilvusPolicyStore.user_collection_name(user_id)
    store = FakeMilvusStore(collection_name=expected_collection)
    debug_service = ChunkDebugService(
        debug_root=tmp_path / "chunks_debug",
        preview_root=tmp_path / "chunks_preview",
    )

    service = PolicyIngestionService(
        session=session,
        embedding_service=FakeEmbeddingService(),
        chunk_debug_service=debug_service,
        milvus_store=store,
        owner_user_id=user_id,
        collection_name=expected_collection,
    )

    from app.gwy.services import policy_ingestion_service as ingestion_module

    monkeypatch.setattr(
        ingestion_module,
        "load_pdf_pages",
        lambda file_path: [
            {
                "page": 1,
                "text": "Question: How do I upload files?\n"
                "Answer: Use the user-specific upload collection.",
            }
        ],
    )
    monkeypatch.setattr(
        ingestion_module,
        "analyze_pdf_layout",
        lambda file_path: {"pages": [{"page": 1, "blocks": []}]},
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_image_assets",
        lambda file_path, layout_pages=None: [],
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_tables",
        lambda file_path, layout_pages=None: {"tables": [], "rows": [], "chunks": []},
    )

    result = service.ingest_policy_pdf(
        "data/user_uploads/note.pdf",
        owner_user_id=user_id,
        collection_name=expected_collection,
    )

    assert result["milvus_collection"] == expected_collection
    assert result["chunk_stats"]["total_chunks"] == 1
    assert store.created is True
    assert len(store.inserted) == 1
    assert session.added[0].milvus_collection == expected_collection


def test_policy_ingestion_service_deduplicates_duplicate_table_rows(
    monkeypatch,
    tmp_path,
) -> None:
    from app.gwy.services import policy_ingestion_service as ingestion_module

    monkeypatch.setattr(
        ingestion_module,
        "load_pdf_pages",
        lambda file_path: [
            {
                "page": 1,
                "text": "问：如何打印准考证？\n答：请登录报名系统打印。",
            }
        ],
    )
    monkeypatch.setattr(
        ingestion_module,
        "analyze_pdf_layout",
        lambda file_path: {"pages": [{"page": 1, "blocks": []}]},
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_image_assets",
        lambda file_path, layout_pages=None: [],
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_tables",
        lambda file_path, layout_pages=None: {
            "tables": [
                {
                    "table_id": "11111111-1111-1111-1111-111111111111",
                    "source_file": file_path,
                    "page_start": 1,
                    "page_end": 1,
                    "bbox": [0, 0, 10, 10],
                    "columns": ["字段1", "字段2"],
                    "rows": [["有效字段", "值"]],
                    "markdown_content": "| 字段1 | 字段2 |\n| --- | --- |\n| 有效字段 | 值 |",
                    "table_image_path": "",
                    "extraction_status": "success",
                    "is_cross_page": False,
                    "source_pages": [1],
                    "linked_chunk_ids": [],
                }
            ],
            "rows": [],
            "chunks": [
                {
                    "chunk_id": "row-1",
                    "chunk_type": "table_row",
                    "content": "字段1：有效字段；字段2：值",
                    "question": "",
                    "section": "",
                    "asset_type": "table",
                    "table_id": "11111111-1111-1111-1111-111111111111",
                    "row_id": "row-a",
                    "table_image_path": "",
                    "page_start": 1,
                    "page_end": 1,
                    "bbox_list": [[0, 0, 10, 10]],
                        "metadata": {
                            "source_file": file_path,
                            "table_id": "11111111-1111-1111-1111-111111111111",
                            "row_id": "row-a",
                            "page_start": 1,
                            "page_end": 1,
                            "asset_type": "table",
                            "columns": ["字段1", "字段2"],
                        },
                    },
                {
                    "chunk_id": "row-2",
                    "chunk_type": "table_row",
                    "content": "字段1：有效字段；字段2：值",
                    "question": "",
                    "section": "",
                    "asset_type": "table",
                    "table_id": "11111111-1111-1111-1111-111111111111",
                    "row_id": "row-b",
                    "table_image_path": "",
                    "page_start": 1,
                    "page_end": 1,
                    "bbox_list": [[0, 0, 10, 10]],
                        "metadata": {
                            "source_file": file_path,
                            "table_id": "11111111-1111-1111-1111-111111111111",
                            "row_id": "row-b",
                            "page_start": 1,
                            "page_end": 1,
                            "asset_type": "table",
                            "columns": ["字段1", "字段2"],
                        },
                    },
                ],
            },
        )

    session = FakeSession()
    store = FakeMilvusStore()
    debug_service = ChunkDebugService(
        debug_root=tmp_path / "chunks_debug",
        preview_root=tmp_path / "chunks_preview",
    )
    service = PolicyIngestionService(
        session=session,
        embedding_service=FakeEmbeddingService(),
        chunk_debug_service=debug_service,
        milvus_store=store,
    )

    result = service.ingest_policy_pdf("data/考务问答/如何打印准考证.pdf")

    assert result["success"] is True
    assert result["chunk_count"] == 2
    assert len(store.inserted) == 2


def test_policy_ingestion_service_strips_layout_chrome_when_building_pages(
    monkeypatch,
    tmp_path,
) -> None:
    from app.gwy.services import policy_ingestion_service as ingestion_module

    captured_pages: list[dict[str, object]] = []

    def fake_chunk_policy_document(*, pages, doc_group, doc_type, base_metadata):
        captured_pages.extend(pages)
        return [
            {
                "chunk_id": "chunk-1",
                "content": "正文段落",
                "question": "",
                "section": "第一节",
                "chunk_type": "policy_section",
                "asset_type": "text",
                "page_start": 1,
                "page_end": 1,
                "metadata": {
                    "source_file": base_metadata["source_file"],
                    "doc_group": doc_group,
                    "doc_type": doc_type,
                },
            }
        ]

    monkeypatch.setattr(
        ingestion_module,
        "load_pdf_pages",
        lambda file_path: (_ for _ in ()).throw(RuntimeError("force layout fallback")),
    )
    monkeypatch.setattr(
        ingestion_module,
        "analyze_pdf_layout",
        lambda file_path: {
            "pages": [
                {
                    "page": 1,
                    "blocks": [
                        {"block_type": "header", "text": "首页 > 招考公告 > 招考公告"},
                        {"block_type": "text", "text": "返回顶部 咨询电话 <<"},
                        {"block_type": "text", "text": "正文段落"},
                        {"block_type": "footer", "text": "版权所有 国家公务员局"},
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(
        ingestion_module,
        "chunk_policy_document",
        fake_chunk_policy_document,
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_image_assets",
        lambda file_path, layout_pages=None: [],
    )
    monkeypatch.setattr(
        ingestion_module,
        "extract_pdf_tables",
        lambda file_path, layout_pages=None: {"tables": [], "rows": [], "chunks": []},
    )

    session = FakeSession()
    store = FakeMilvusStore()
    debug_service = ChunkDebugService(
        debug_root=tmp_path / "chunks_debug",
        preview_root=tmp_path / "chunks_preview",
    )
    service = PolicyIngestionService(
        session=session,
        embedding_service=FakeEmbeddingService(),
        chunk_debug_service=debug_service,
        milvus_store=store,
    )

    result = service.ingest_policy_pdf("data/policy_qa/example.pdf")

    assert result["success"] is True
    assert captured_pages == [{"page": 1, "text": "正文段落"}]


def test_policy_ingestion_service_filters_low_quality_noise_chunk(tmp_path) -> None:
    session = FakeSession()
    store = FakeMilvusStore()
    debug_service = ChunkDebugService(
        debug_root=tmp_path / "chunks_debug",
        preview_root=tmp_path / "chunks_preview",
    )
    service = PolicyIngestionService(
        session=session,
        embedding_service=FakeEmbeddingService(),
        chunk_debug_service=debug_service,
        milvus_store=store,
    )

    chunks = [
        {
            "chunk_id": "noise-1",
            "chunk_type": "policy_qa",
            "content": "问：1\n答：6",
            "question": "1",
            "answer": "6",
            "source_file": "data/noise.pdf",
            "page_start": 1,
            "page_end": 1,
            "metadata": {"source_file": "data/noise.pdf"},
        },
        {
            "chunk_id": "ok-1",
            "chunk_type": "policy_qa",
            "content": "问：如何打印准考证？\n答：登录专题网站打印。",
            "question": "如何打印准考证？",
            "answer": "登录专题网站打印。",
            "source_file": "data/ok.pdf",
            "page_start": 1,
            "page_end": 1,
            "metadata": {"source_file": "data/ok.pdf"},
        },
    ]

    filtered = service._deduplicate_chunks(chunks)

    assert len(filtered) == 1
    assert filtered[0]["chunk_id"] == "ok-1"
