from app.gwy.document.chunker import chunk_policy_document


def test_chunk_qa_document_prefers_question_answer_pairs() -> None:
    pages = [
        {
            "page": 1,
            "text": "\u95ee\uff1a\u5982\u4f55\u6253\u5370\u51c6\u8003\u8bc1\uff1f\n\u7b54\uff1a\u8bf7\u5728\u89c4\u5b9a\u65f6\u95f4\u5185\u767b\u5f55\u7cfb\u7edf\u6253\u5370\u3002",
        }
    ]
    chunks = chunk_policy_document(
        pages=pages,
        doc_group="exam_affairs_qa",
        doc_type="admission_ticket",
        base_metadata={
            "year": 2026,
            "exam_type": "national",
            "province": "national",
            "doc_group": "exam_affairs_qa",
            "doc_type": "admission_ticket",
            "doc_title": "\u5982\u4f55\u6253\u5370\u51c6\u8003\u8bc1",
            "source_file": "data/\u8003\u52a1\u95ee\u7b54/\u5982\u4f55\u6253\u5370\u51c6\u8003\u8bc1.pdf",
            "source": "official",
        },
    )

    assert len(chunks) == 1
    assert chunks[0]["question"] == "\u5982\u4f55\u6253\u5370\u51c6\u8003\u8bc1\uff1f"
    assert chunks[0]["chunk_type"] == "text_qa"
    assert chunks[0]["asset_type"] == "text"
    assert (
        "\u95ee\u9898\uff1a\u5982\u4f55\u6253\u5370\u51c6\u8003\u8bc1\uff1f"
        in chunks[0]["content"]
    )
    assert (
        "\u56de\u7b54\uff1a\u8bf7\u5728\u89c4\u5b9a\u65f6\u95f4\u5185\u767b\u5f55\u7cfb\u7edf\u6253\u5370\u3002"
        in chunks[0]["content"]
    )
    assert chunks[0]["page_start"] == 1
    assert chunks[0]["page_end"] == 1


def test_chunk_announcement_by_heading() -> None:
    pages = [
        {
            "page": 1,
            "text": "\u4e00\u3001\u62a5\u540d\u6761\u4ef6\n\u7b2c\u4e00\u6bb5\u5185\u5bb9\u3002\n\u4e8c\u3001\u8003\u8bd5\u5b89\u6392\n\u7b2c\u4e8c\u6bb5\u5185\u5bb9\u3002",
        }
    ]
    chunks = chunk_policy_document(
        pages=pages,
        doc_group="announcement",
        doc_type="recruitment_announcement",
        base_metadata={
            "year": 2026,
            "exam_type": "national",
            "province": "national",
            "doc_group": "announcement",
            "doc_type": "recruitment_announcement",
            "doc_title": "\u56fd\u8003\u516c\u544a",
            "source_file": "data/2026_\u56fd\u8003\u516c\u544a.pdf",
            "source": "official",
        },
    )

    assert len(chunks) == 2
    assert chunks[0]["section"].startswith("\u4e00\u3001\u62a5\u540d\u6761\u4ef6")
    assert chunks[1]["section"].startswith("\u4e8c\u3001\u8003\u8bd5\u5b89\u6392")
    assert chunks[0]["chunk_type"] == "text_clause"
    assert chunks[1]["chunk_type"] == "text_clause"


def test_chunk_outline_by_module() -> None:
    pages = [
        {
            "page": 1,
            "text": "\u884c\u653f\u804c\u4e1a\u80fd\u529b\u6d4b\u9a8c\n\u901a\u8bc6\u80fd\u529b\u5185\u5bb9\u3002\n\u7533\u8bba\n\u5b9e\u8df5\u80fd\u529b\u5185\u5bb9\u3002",
        }
    ]
    chunks = chunk_policy_document(
        pages=pages,
        doc_group="exam_outline",
        doc_type="public_subject_outline",
        base_metadata={
            "year": 2026,
            "exam_type": "national",
            "province": "national",
            "doc_group": "exam_outline",
            "doc_type": "public_subject_outline",
            "doc_title": "\u516c\u5171\u79d1\u76ee\u8003\u8bd5\u5927\u7eb2",
            "source_file": "data/2026_\u516c\u5171\u79d1\u76ee\u8003\u8bd5\u5927\u7eb2.pdf",
            "source": "official",
        },
    )

    assert len(chunks) == 2
    assert "\u884c\u653f\u804c\u4e1a\u80fd\u529b\u6d4b\u9a8c" in chunks[0]["section"]
    assert "\u7533\u8bba" in chunks[1]["section"]
    assert chunks[0]["chunk_type"] == "text_module"
    assert chunks[1]["chunk_type"] == "text_module"


def test_chunk_major_catalog_by_structure() -> None:
    pages = [
        {
            "page": 1,
            "text": "\u4e13\u4e1a\u5927\u7c7b\uff1a\u6cd5\u5b66\n\u5b66\u79d1\u95e8\u7c7b\uff1a\u6cd5\u5b66\n\u4e13\u4e1a\u6761\u76ee\uff1a\u6cd5\u5b66\u4e13\u4e1a\u3002",
        }
    ]
    chunks = chunk_policy_document(
        pages=pages,
        doc_group="major_catalog",
        doc_type="major_catalog",
        base_metadata={
            "year": 2026,
            "exam_type": "national",
            "province": "national",
            "doc_group": "major_catalog",
            "doc_type": "major_catalog",
            "doc_title": "\u4e13\u4e1a\u76ee\u5f55",
            "source_file": "data/\u4e13\u4e1a\u76ee\u5f55.pdf",
            "source": "official",
        },
    )

    assert len(chunks) == 3
    assert all(chunk["chunk_type"] == "text_clause" for chunk in chunks)
