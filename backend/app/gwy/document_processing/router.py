from __future__ import annotations

import re
from typing import Any

from app.gwy.document_processing.extractors import (
    has_question_answer_structure,
    normalize_text,
    parse_table_from_text,
)
from app.gwy.document_processing.schemas import BlockType


TABLE_KEYWORDS = (
    "机构名称",
    "咨询电话",
    "地址",
    "单位名称",
    "岗位代码",
    "职位代码",
    "专业要求",
    "学历",
    "学位",
    "备注",
)
EXAM_ITEM_KEYWORDS = (
    "根据图示",
    "下图",
    "图片",
    "图形",
    "图表",
    "材料一",
    "材料二",
)
SECTION_KEYWORDS = (
    "第一条",
    "第二条",
    "第三条",
    "第四条",
    "一、",
    "二、",
    "三、",
    "（一）",
    "（二）",
    "（三）",
)


def classify_content_block(text: str, metadata: dict[str, Any]) -> BlockType:
    normalized = normalize_text(text)
    image_refs = list(metadata.get("image_refs") or [])
    row_id = metadata.get("row_id")
    chunk_level = str(metadata.get("chunk_level") or "")
    block_type_hint = str(metadata.get("block_type") or "")

    if chunk_level == "row" or row_id or block_type_hint == "table_row":
        return BlockType.TABLE_ROW
    if not normalized and image_refs:
        return BlockType.IMAGE_BLOCK
    if _looks_like_exam_item(normalized, metadata):
        return BlockType.EXAM_ITEM_MULTIMODAL
    if _looks_like_policy_qa(normalized, metadata):
        return BlockType.POLICY_QA
    if _looks_like_table(normalized, metadata):
        return BlockType.TABLE
    if _looks_like_policy_section(normalized, metadata):
        return BlockType.POLICY_SECTION
    return BlockType.SEMANTIC_TEXT


def _looks_like_table(text: str, metadata: dict[str, Any]) -> bool:
    if has_question_answer_structure(text):
        return False
    if str(metadata.get("table_id") or ""):
        return True

    parsed = parse_table_from_text(text)
    if parsed:
        return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    table_like_lines = sum(1 for line in lines if _line_looks_table_like(line))
    if table_like_lines < 2:
        return False

    column_counts = [_estimated_columns(line) for line in lines if _line_looks_table_like(line)]
    if not column_counts:
        return False
    if max(column_counts) < 2:
        return False
    if len(set(column_counts)) > 2:
        return False
    if any(_contains_qa_markers(line) for line in lines):
        return False
    return True


def _looks_like_exam_item(text: str, metadata: dict[str, Any]) -> bool:
    if list(metadata.get("image_refs") or []):
        return True
    if any(keyword in text for keyword in EXAM_ITEM_KEYWORDS):
        if any(option in text for option in ["A.", "B.", "C.", "D.", "A、", "B、", "C、", "D、"]):
            return True
    if re.search(r"(?:[A-D][\.\uff0c、])", text) and "题" in text:
        return True
    return False


def _looks_like_policy_qa(text: str, metadata: dict[str, Any]) -> bool:
    if has_question_answer_structure(text):
        return True
    if str(metadata.get("doc_group") or "") in {"technical_qa", "exam_affairs_qa", "policy_qa"}:
        if "问" in text and "答" in text:
            return True
    return False


def _looks_like_policy_section(text: str, metadata: dict[str, Any]) -> bool:
    if not text:
        return False
    if any(keyword in text for keyword in SECTION_KEYWORDS):
        return True
    if str(metadata.get("doc_group") or "") in {"announcement", "exam_outline"}:
        return True
    if len(text) >= 80 and not _contains_qa_markers(text):
        return True
    return False


def _line_looks_table_like(line: str) -> bool:
    return _estimated_columns(line) >= 2


def _estimated_columns(line: str) -> int:
    if "|" in line:
        return len([cell for cell in line.split("|") if cell.strip()])
    if "\t" in line:
        return len([cell for cell in line.split("\t") if cell.strip()])
    if re.search(r"\s{2,}", line):
        return len([cell for cell in re.split(r"\s{2,}", line) if cell.strip()])
    if re.search(r"[，,、；;]", line) and len(line) < 100:
        return max(2, len(re.split(r"[，,、；;]", line)))
    return 1


def _contains_qa_markers(line: str) -> bool:
    return bool(re.search(r"(?:问[:：]|问题[:：]|答[:：]|回答[:：]|Q[:：]|A[:：])", line))

