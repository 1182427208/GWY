from __future__ import annotations

from app.gwy.services.chunk_debug_service import ChunkDebugService


def test_chunk_debug_service_exports_artifacts_and_stats(tmp_path) -> None:
    service = ChunkDebugService(
        debug_root=tmp_path / "chunks_debug",
        preview_root=tmp_path / "chunks_preview",
    )
    metadata = {
        "year": 2026,
        "exam_type": "national",
        "province": "national",
        "doc_group": "exam_affairs_qa",
        "doc_type": "admission_ticket",
        "doc_title": "How to print the admission ticket",
        "source_file": "data/exam_affairs_qa/how_to_print_ticket.pdf",
    }
    result = service.export_pdf_chunks(
        source_file=metadata["source_file"],
        chunks=[
            {
                "chunk_id": "chunk-1",
                "content": "Question: How do I print the admission ticket?\nAnswer: Log in first.",
                "question": "How do I print the admission ticket?",
                "section": "Admission ticket",
                "chunk_type": "qa_pair",
                "page_start": 1,
                "page_end": 1,
                "metadata": metadata,
            }
        ],
        metadata=metadata,
    )

    jsonl_path = tmp_path / "chunks_debug" / "data__exam_affairs_qa__how_to_print_ticket.pdf.chunks.jsonl"
    csv_path = tmp_path / "chunks_debug" / "data__exam_affairs_qa__how_to_print_ticket.pdf.chunks.csv"
    preview_path = (
        tmp_path / "chunks_preview" / "data__exam_affairs_qa__how_to_print_ticket.pdf.preview.html"
    )

    assert jsonl_path.exists()
    assert csv_path.exists()
    assert preview_path.exists()
    assert result["chunk_stats"]["total_chunks"] == 1
    assert result["chunk_stats"]["fallback_ratio"] == 0.0
    assert result["warnings"] == []

    records = service.list_chunks()
    assert len(records) == 1
    assert records[0]["chunk_id"] == "chunk-1"
    assert service.get_chunk("chunk-1") is not None
    stats = service.get_chunk_stats()
    assert stats["total_chunks"] == 1
