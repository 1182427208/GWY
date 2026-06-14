from __future__ import annotations

from app.api.routes import gwy as gwy_routes
from app.core.config import settings
from app.gwy.services.chunk_debug_service import ChunkDebugService


def test_chunk_debug_endpoints_expose_artifacts(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    service = ChunkDebugService(
        debug_root=tmp_path / "chunks_debug",
        preview_root=tmp_path / "chunks_preview",
    )
    service.export_pdf_chunks(
        source_file="data/exam_affairs_qa/how_to_print_ticket.pdf",
        chunks=[
            {
                "chunk_id": "chunk-1",
                "content": "Question: How do I print the admission ticket?\nAnswer: Log in first.",
                "question": "How do I print the admission ticket?",
                "section": "Admission ticket",
                "chunk_type": "qa_pair",
                "page_start": 1,
                "page_end": 1,
                "metadata": {
                    "year": 2026,
                    "exam_type": "national",
                    "province": "national",
                    "doc_group": "exam_affairs_qa",
                    "doc_type": "admission_ticket",
                    "doc_title": "How to print the admission ticket",
                    "source_file": "data/exam_affairs_qa/how_to_print_ticket.pdf",
                },
            }
        ],
        metadata={
            "year": 2026,
            "exam_type": "national",
            "province": "national",
            "doc_group": "exam_affairs_qa",
            "doc_type": "admission_ticket",
            "doc_title": "How to print the admission ticket",
            "source_file": "data/exam_affairs_qa/how_to_print_ticket.pdf",
        },
    )

    monkeypatch.setattr(gwy_routes, "ChunkDebugService", lambda: service)

    list_response = client.get(f"{settings.API_V1_STR}/gwy/debug/chunks")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert list_payload["data"][0]["chunk_id"] == "chunk-1"

    detail_response = client.get(f"{settings.API_V1_STR}/gwy/debug/chunks/chunk-1")
    assert detail_response.status_code == 200
    assert detail_response.json()["chunk_id"] == "chunk-1"

    stats_response = client.get(f"{settings.API_V1_STR}/gwy/debug/chunk-stats")
    assert stats_response.status_code == 200
    stats_payload = stats_response.json()
    assert stats_payload["total_chunks"] == 1
    assert stats_payload["fallback_ratio"] == 0.0
