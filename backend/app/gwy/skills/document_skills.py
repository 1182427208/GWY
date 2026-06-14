from __future__ import annotations

from typing import Any

from app.gwy.document_processing.chunkers import (
    build_policy_section_chunks_skill as _build_policy_section_chunks_skill,
    build_table_row_chunks_skill as _build_table_row_chunks_skill,
    chunk_quality_guard_skill as _chunk_quality_guard_skill,
    chunk_semantic_text as _chunk_semantic_text,
    classify_block_skill as _classify_block_skill,
    extract_exam_item_skill as _extract_exam_item_skill,
    extract_policy_qa_skill as _extract_policy_qa_skill,
    extract_table_skill as _extract_table_skill,
)


def classify_block_skill(text: str, metadata: dict[str, Any]) -> str:
    return _classify_block_skill(text, metadata)


def extract_policy_qa_skill(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_policy_qa_skill(text, metadata)


def extract_table_skill(table_data: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_table_skill(table_data, metadata)


def build_table_row_chunks_skill(
    table_data: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return _build_table_row_chunks_skill(table_data, metadata)


def extract_exam_item_skill(
    text: str,
    image_refs: list[str],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return _extract_exam_item_skill(text, image_refs, metadata)


def build_policy_section_chunks_skill(
    text: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return _build_policy_section_chunks_skill(text, metadata)


def chunk_quality_guard_skill(chunks: list[dict[str, Any]]) -> list[str]:
    return _chunk_quality_guard_skill(chunks)


def chunk_semantic_text_skill(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return _chunk_semantic_text(text, metadata)

