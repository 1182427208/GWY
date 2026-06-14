from __future__ import annotations

from typing import Any

from app.gwy.document_processing.chunkers import chunk_policy_document as _chunk_policy_document


def chunk_policy_document(
    pages: list[dict[str, Any]],
    doc_group: str,
    doc_type: str,
    base_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    chunks = _chunk_policy_document(
        pages=pages,
        doc_group=doc_group,
        doc_type=doc_type,
        base_metadata=base_metadata,
    )
    return [_normalize_chunk(chunk, doc_group=doc_group, doc_type=doc_type) for chunk in chunks]


def _normalize_chunk(
    chunk: dict[str, Any],
    *,
    doc_group: str,
    doc_type: str,
) -> dict[str, Any]:
    normalized = dict(chunk)
    source_type = str(normalized.get("chunk_type") or "")
    if source_type == "policy_qa":
        normalized["chunk_type"] = "text_qa"
        content = str(normalized.get("content") or "")
        if content:
            content = content.replace("问：", "问题：").replace("答：", "回答：")
            normalized["content"] = content
    elif source_type == "policy_section":
        if doc_group == "exam_outline" or doc_type in {"public_subject_outline", "professional_subject_outline"}:
            normalized["chunk_type"] = "text_module"
        else:
            normalized["chunk_type"] = "text_clause"
    elif source_type == "semantic_text":
        normalized["chunk_type"] = "text_clause"

    section = str(
        normalized.get("section")
        or normalized.get("heading")
        or normalized.get("title")
        or " > ".join(str(item).strip() for item in normalized.get("section_path") or [] if str(item).strip())
        or str(normalized.get("content") or "").splitlines()[0].strip()
    ).strip()
    if section:
        normalized["section"] = section
    normalized.setdefault("asset_type", "text")
    return normalized
