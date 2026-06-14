from __future__ import annotations

from typing import Any

from app.gwy.skills.document_skills import (
    build_policy_section_chunks_skill,
    build_table_row_chunks_skill,
    chunk_quality_guard_skill,
    classify_block_skill,
    extract_exam_item_skill,
    extract_policy_qa_skill,
    extract_table_skill,
)


def document_chunk_mcp(payload: dict[str, Any]) -> dict[str, Any]:
    chunks = payload.get("chunks") or []
    return {"chunks": chunks, "chunk_count": len(chunks)}


def policy_qa_extract_mcp(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return extract_policy_qa_skill(text, metadata)


def table_extract_mcp(table_data: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return extract_table_skill(table_data, metadata)


def exam_item_extract_mcp(
    text: str,
    image_refs: list[str],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return extract_exam_item_skill(text, image_refs, metadata)


def build_policy_section_chunks_mcp(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return build_policy_section_chunks_skill(text, metadata)


def build_table_row_chunks_mcp(table_data: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return build_table_row_chunks_skill(table_data, metadata)


def chunk_quality_guard_mcp(chunks: list[dict[str, Any]]) -> list[str]:
    return chunk_quality_guard_skill(chunks)


def classify_block_mcp(text: str, metadata: dict[str, Any]) -> str:
    return classify_block_skill(text, metadata)

