from __future__ import annotations

from app.gwy.document_processing.chunkers import (
    chunk_exam_item_multimodal,
    chunk_policy_qa,
    chunk_policy_section,
    chunk_semantic_text,
    chunk_table,
)
from app.gwy.document_processing.extractors import parse_qa_pairs
from app.gwy.document_processing.guards import (
    chunk_citation_guard,
    chunk_noise_guard,
    exam_item_guard,
    is_placeholder_noise_chunk,
    no_split_question_answer_guard,
    qa_pair_guard,
    table_guard,
)
from app.gwy.document_processing.router import BlockType, classify_content_block


def test_classify_real_table_as_table() -> None:
    text = (
        "机构名称 | 咨询电话 | 地址\n"
        "国家税务总局 | 12345 | 北京市\n"
        "人社部 | 67890 | 北京市"
    )
    block_type = classify_content_block(
        text,
        {"doc_group": "policy_section", "source_category": "official"},
    )
    assert block_type == BlockType.TABLE


def test_classify_qa_prioritizes_question_answer_over_table_like_rows() -> None:
    text = (
        "问：如何打印准考证？\n"
        "答：请在规定时间内登录报名系统打印。\n"
        "问：忘记密码怎么办？\n"
        "答：使用找回密码功能重置。"
    )
    block_type = classify_content_block(
        text,
        {"doc_group": "policy_qa", "source_category": "official"},
    )
    assert block_type == BlockType.POLICY_QA


def test_classify_numbered_qa_as_policy_qa() -> None:
    text = (
        "1. 如何打印准考证？\n"
        "答：请在规定时间内登录报名系统打印。\n"
        "2. 忘记密码怎么办？\n"
        "答：使用找回密码功能重置。"
    )
    block_type = classify_content_block(
        text,
        {"doc_group": "policy_qa", "source_category": "official"},
    )
    assert block_type == BlockType.POLICY_QA


def test_parse_qa_pairs_supports_numbered_questions() -> None:
    pairs = parse_qa_pairs(
        "1. 如何打印准考证？\n"
        "答：请在规定时间内登录报名系统打印。\n"
        "2. 忘记密码怎么办？\n"
        "答：使用找回密码功能重置。"
    )

    assert len(pairs) == 2
    assert pairs[0]["question"].startswith("如何打印准考证")
    assert "找回密码功能重置" in pairs[1]["answer"]


def test_classify_exam_item_multimodal_with_image_refs() -> None:
    text = "根据图示，判断下一步最合理的操作。A. ... B. ... C. ... D. ..."
    block_type = classify_content_block(
        text,
        {"image_refs": ["img-1"], "source_category": "official"},
    )
    assert block_type == BlockType.EXAM_ITEM_MULTIMODAL


def test_classify_policy_section_for_plain_prose() -> None:
    text = "第一条 申请人应当如实填写报名信息。第二条 报名信息一经提交，不得随意修改。"
    block_type = classify_content_block(
        text,
        {"doc_group": "announcement", "source_category": "official"},
    )
    assert block_type == BlockType.POLICY_SECTION


def test_classify_semantic_text_as_fallback() -> None:
    text = "这是一段没有明显结构的普通说明文字，主要用于兜底切分。"
    block_type = classify_content_block(
        text,
        {"doc_group": "unknown", "source_category": "official"},
    )
    assert block_type == BlockType.SEMANTIC_TEXT


def test_chunk_policy_qa_keeps_question_and_answer_together() -> None:
    chunks = chunk_policy_qa(
        text=(
            "问：如何打印准考证？\n"
            "答：请在规定时间内登录报名系统打印，并核对信息。\n"
            "问：忘记密码怎么办？\n"
            "答：使用找回密码功能重置。"
        ),
        metadata={
            "source_file": "data/考务问答/如何打印准考证.pdf",
            "doc_type": "admission_ticket",
            "source_category": "official",
            "section_path": ["考务问答"],
            "page_start": 1,
            "page_end": 1,
        },
    )

    assert len(chunks) == 2
    assert chunks[0]["chunk_type"] == "policy_qa"
    assert chunks[0]["question"] == "如何打印准考证？"
    assert "问：如何打印准考证？" in chunks[0]["content"]
    assert "答：请在规定时间内登录报名系统打印，并核对信息。" in chunks[0]["content"]


def test_chunk_table_builds_table_and_row_chunks() -> None:
    chunks = chunk_table(
        table_data={
            "title": "咨询电话表",
            "columns": ["机构名称", "咨询电话", "地址"],
            "rows": [
                ["国家税务总局", "12345", "北京市"],
                ["人社部", "67890", "北京市"],
            ],
            "page_start": 2,
            "page_end": 2,
        },
        metadata={
            "source_file": "data/报考指南/联系电话表.pdf",
            "doc_type": "registration_policy",
            "source_category": "official",
            "section_path": ["报考指南", "联系方式"],
            "page_start": 2,
            "page_end": 2,
        },
    )

    assert len(chunks) == 3
    assert chunks[0]["chunk_type"] == "table"
    assert {chunk["chunk_type"] for chunk in chunks[1:]} == {"table_row"}


def test_chunk_exam_item_multimodal_preserves_image_refs() -> None:
    chunks = chunk_exam_item_multimodal(
        text="根据图片中的图形规律，选择正确答案。A. ... B. ... C. ... D. ...",
        image_refs=["img-1", "img-2"],
        metadata={
            "source_file": "data/题目截图/1.png",
            "doc_type": "other_policy",
            "source_category": "official",
            "section_path": ["题目截图"],
            "page_start": 1,
            "page_end": 1,
        },
    )

    assert len(chunks) == 1
    assert chunks[0]["chunk_type"] == "exam_item_multimodal"
    assert chunks[0]["image_refs"] == ["img-1", "img-2"]


def test_chunk_policy_section_falls_back_to_section_chunks() -> None:
    chunks = chunk_policy_section(
        text=(
            "第一条 申请人应当如实填写报名信息。\n"
            "第二条 相关材料应当真实、准确、完整。"
        ),
        metadata={
            "source_file": "data/2026_国考公告.pdf",
            "doc_type": "recruitment_announcement",
            "source_category": "official",
            "section_path": ["公告"],
            "page_start": 1,
            "page_end": 1,
        },
    )

    assert len(chunks) == 2
    assert all(chunk["chunk_type"] == "policy_section" for chunk in chunks)


def test_chunk_semantic_text_is_fallback_only() -> None:
    chunks = chunk_semantic_text(
        text="这是一段没有结构的说明文字。这里继续补充一句。",
        metadata={
            "source_file": "data/other.pdf",
            "doc_type": "other_policy",
            "source_category": "official",
            "section_path": [],
            "page_start": 1,
            "page_end": 1,
        },
    )

    assert len(chunks) == 1
    assert chunks[0]["chunk_type"] == "semantic_text"


def test_guards_validate_required_fields() -> None:
    qa_chunk = {
        "chunk_type": "policy_qa",
        "question": "如何打印准考证？",
        "answer": "请登录系统打印。",
        "source_file": "data/考务问答/如何打印准考证.pdf",
        "page_start": 1,
        "page_end": 1,
        "bbox": [1, 2, 3, 4],
    }
    table_chunk = {
        "chunk_type": "table",
        "columns": ["A", "B"],
        "rows": [["1", "2"]],
        "source_file": "data/table.pdf",
        "page_start": 1,
        "page_end": 1,
        "bbox": [1, 2, 3, 4],
    }
    exam_chunk = {
        "chunk_type": "exam_item_multimodal",
        "stem": "根据图片选择答案",
        "image_refs": ["img-1"],
        "source_file": "data/item.png",
        "page_start": 1,
        "page_end": 1,
        "bbox": [1, 2, 3, 4],
    }

    assert qa_pair_guard(qa_chunk) is True
    assert table_guard(table_chunk) is True
    assert exam_item_guard(exam_chunk) is True
    assert chunk_citation_guard(qa_chunk) is True
    assert no_split_question_answer_guard(qa_chunk) is True


def test_placeholder_noise_guard_flags_numeric_qa_noise() -> None:
    assert (
        is_placeholder_noise_chunk(
            {
                "chunk_type": "policy_qa",
                "content": "问：1\n答：6",
            }
        )
        is True
    )


def test_placeholder_noise_guard_flags_navigation_table_noise() -> None:
    chunk = {
        "chunk_type": "table_summary",
        "content": (
            "表头列：首页 招考公告 政策法规、常见问题、相关下载 公告公示 个人中心\n"
            "表格结构：| 首页 招考公告 政策法规 | 常见问题 | 相关下载 公告公示 个人中心 |\n"
            "| --- | --- | --- |\n"
            "|  | None | None |"
        ),
    }
    assert is_placeholder_noise_chunk(chunk) is True
    assert chunk_noise_guard(chunk) is False
