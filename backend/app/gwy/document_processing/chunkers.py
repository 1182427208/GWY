from __future__ import annotations

import re
import uuid
from typing import Any

from app.gwy.document_processing.extractors import (
    make_content_hash,
    normalize_text,
    parse_qa_pairs,
    parse_table_from_text,
    split_heading_sections,
    split_semantic_text,
    table_rows_to_markdown,
)
from app.gwy.document_processing.guards import (
    chunk_citation_guard,
    chunk_noise_guard,
    exam_item_guard,
    no_split_question_answer_guard,
    qa_pair_guard,
    table_guard,
)
from app.gwy.document_processing.router import classify_content_block
from app.gwy.document_processing.schemas import BlockType


def chunk_policy_qa(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    pairs = [
        pair
        for pair in parse_qa_pairs(text)
        if str(pair.get("question") or "").strip() and str(pair.get("answer") or "").strip()
    ]
    if not pairs:
        fallback_pair = _extract_single_qa_pair(text, metadata)
        if fallback_pair:
            pairs = [fallback_pair]

    chunks: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        question = str(pair.get("question") or "").strip()
        answer = str(pair.get("answer") or "").strip()
        content = str(pair.get("content") or f"问：{question}\n答：{answer}").strip()
        chunk = _build_chunk(
            chunk_type=BlockType.POLICY_QA,
            metadata=metadata,
            content=content,
            question=question,
            answer=answer,
            page_start=int(metadata.get("page_start", 0) or 0),
            page_end=int(metadata.get("page_end", 0) or 0),
            section_path=list(metadata.get("section_path") or []),
            title=str(metadata.get("title") or ""),
            retrieval_queries=_build_retrieval_queries(question, metadata),
            evidence_refs=list(metadata.get("evidence_refs") or []),
            extra={
                "question": question,
                "answer": answer,
                "pair_index": index,
            },
        )
        if (
            qa_pair_guard(chunk)
            and no_split_question_answer_guard(chunk)
            and chunk_citation_guard(chunk)
            and chunk_noise_guard(chunk)
        ):
            chunks.append(chunk)
    return chunks


def chunk_table(table_data: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    columns = _normalize_columns(table_data.get("columns") or [])
    rows = _normalize_rows(table_data.get("rows") or [])
    if not columns and rows:
        columns = [f"col_{index + 1}" for index in range(max(len(row) for row in rows))]

    markdown = str(
        table_data.get("markdown_content")
        or table_rows_to_markdown(columns, rows)
    ).strip()
    table_title = str(table_data.get("title") or metadata.get("title") or "").strip()
    section_path = list(metadata.get("section_path") or [])
    table_chunk = _build_chunk(
        chunk_type=BlockType.TABLE,
        metadata=metadata,
        content=markdown,
        question="",
        answer="",
        page_start=int(table_data.get("page_start", metadata.get("page_start", 0)) or 0),
        page_end=int(table_data.get("page_end", metadata.get("page_end", 0)) or 0),
        section_path=section_path,
        title=table_title or None,
        retrieval_queries=_build_retrieval_queries(table_title or markdown, metadata),
        evidence_refs=list(metadata.get("evidence_refs") or []),
        extra={
            "table_title": table_title,
            "columns": columns,
            "rows": rows,
        },
    )
    table_chunk["table_title"] = table_title
    table_chunk["columns"] = columns
    table_chunk["rows"] = rows

    chunks: list[dict[str, Any]] = []
    if table_guard(table_chunk) and chunk_noise_guard(table_chunk):
        chunks.append(table_chunk)
    chunks.extend(build_table_row_chunks_skill(table_data, metadata))
    return chunks


def build_table_row_chunks_skill(
    table_data: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    columns = _normalize_columns(table_data.get("columns") or [])
    rows = _normalize_rows(table_data.get("rows") or [])
    chunks: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        if not columns:
            continue
        row_text = "；".join(
            f"{column}：{row[col_index] if col_index < len(row) else ''}"
            for col_index, column in enumerate(columns)
        )
        row_key = f"{str(table_data.get('table_id') or metadata.get('table_id') or 'table')}:{row_index}"
        chunk = _build_chunk(
            chunk_type=BlockType.TABLE_ROW,
            metadata=metadata,
            content=row_text,
            question="",
            answer="",
            page_start=int(table_data.get("page_start", metadata.get("page_start", 0)) or 0),
            page_end=int(table_data.get("page_end", metadata.get("page_end", 0)) or 0),
            section_path=list(metadata.get("section_path") or []),
            title=str(table_data.get("title") or metadata.get("title") or ""),
            retrieval_queries=_build_retrieval_queries(row_text, metadata),
            evidence_refs=list(metadata.get("evidence_refs") or []),
            extra={
                "row_key": row_key,
                "columns": columns,
            },
        )
        chunk["row_key"] = row_key
        chunk["columns"] = columns
        if chunk_citation_guard(chunk) and chunk_noise_guard(chunk):
            chunks.append(chunk)
    return chunks


def chunk_exam_item_multimodal(
    text: str,
    image_refs: list[str],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    stem, options, answer, explanation = _parse_exam_item(normalized)
    chunk = _build_chunk(
        chunk_type=BlockType.EXAM_ITEM_MULTIMODAL,
        metadata=metadata,
        content=normalized,
        question=stem,
        answer=answer or "",
        page_start=int(metadata.get("page_start", 0) or 0),
        page_end=int(metadata.get("page_end", 0) or 0),
        section_path=list(metadata.get("section_path") or []),
        title=str(metadata.get("title") or ""),
        retrieval_queries=_build_retrieval_queries(stem or normalized, metadata),
        evidence_refs=list(metadata.get("evidence_refs") or []),
        extra={
            "question_type": str(metadata.get("question_type") or "multimodal"),
            "stem": stem or normalized,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "image_refs": list(image_refs),
            "ocr_text": str(metadata.get("ocr_text") or ""),
            "visual_description": str(metadata.get("visual_description") or ""),
        },
    )
    chunk["question_type"] = str(metadata.get("question_type") or "multimodal")
    chunk["stem"] = stem or normalized
    chunk["options"] = options
    chunk["image_refs"] = list(image_refs)
    chunk["ocr_text"] = str(metadata.get("ocr_text") or "")
    chunk["visual_description"] = str(metadata.get("visual_description") or "")
    if exam_item_guard(chunk) and chunk_citation_guard(chunk) and chunk_noise_guard(chunk):
        return [chunk]
    return []


def chunk_policy_section(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    sections = split_heading_sections(text)
    if not sections:
        sections = [{"heading": "", "content": normalize_text(text)}]

    chunks: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        content = str(section.get("content") or "").strip()
        if not content:
            continue
        heading = str(section.get("heading") or "").strip()
        clause_id = _detect_clause_id(heading or content)
        chunk = _build_chunk(
            chunk_type=BlockType.POLICY_SECTION,
            metadata=metadata,
            content=content,
            question="",
            answer="",
            page_start=int(metadata.get("page_start", 0) or 0),
            page_end=int(metadata.get("page_end", 0) or 0),
            section_path=list(metadata.get("section_path") or []),
            title=heading or None,
            retrieval_queries=_build_retrieval_queries(heading or content, metadata),
            evidence_refs=list(metadata.get("evidence_refs") or []),
            extra={
                "heading": heading,
                "clause_id": clause_id,
            },
        )
        chunk["chunk_index"] = index
        chunk["heading"] = heading
        chunk["clause_id"] = clause_id
        if chunk_citation_guard(chunk) and chunk_noise_guard(chunk):
            chunks.append(chunk)
    return chunks


def chunk_semantic_text(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    semantic_parts = split_semantic_text(text, chunk_size=700, overlap=150)
    chunks: list[dict[str, Any]] = []
    for index, part in enumerate(semantic_parts):
        chunk = _build_chunk(
            chunk_type=BlockType.SEMANTIC_TEXT,
            metadata=metadata,
            content=part,
            question="",
            answer="",
            page_start=int(metadata.get("page_start", 0) or 0),
            page_end=int(metadata.get("page_end", 0) or 0),
            section_path=list(metadata.get("section_path") or []),
            title=str(metadata.get("title") or ""),
            retrieval_queries=_build_retrieval_queries(part, metadata),
            evidence_refs=list(metadata.get("evidence_refs") or []),
            extra={},
        )
        chunk["chunk_index"] = index
        if chunk_citation_guard(chunk) and chunk_noise_guard(chunk):
            chunks.append(chunk)
    return chunks


def chunk_policy_document(
    pages: list[dict[str, Any]],
    doc_group: str,
    doc_type: str,
    base_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    all_chunks: list[dict[str, Any]] = []
    for page in pages:
        text = normalize_text(str(page.get("text", "")))
        if not text:
            continue

        metadata = dict(base_metadata)
        metadata.update(
            {
                "doc_group": doc_group,
                "doc_type": doc_type,
                "page_start": int(page.get("page", metadata.get("page_start", 0)) or 0),
                "page_end": int(page.get("page", metadata.get("page_end", 0)) or 0),
            }
        )
        block_type = classify_content_block(
            text,
            {
                **metadata,
                "source_category": metadata.get("source_category", "official"),
            },
        )

        if doc_group == "announcement" or doc_type == "recruitment_announcement":
            chunks = chunk_policy_section(text=text, metadata=metadata)
        elif doc_group in {"exam_outline"} or doc_type in {"public_subject_outline", "professional_subject_outline"}:
            chunks = _chunk_outline_sections(text=text, metadata=metadata)
        elif doc_group == "major_catalog" or doc_type == "major_catalog":
            chunks = _chunk_major_catalog_sections(text=text, metadata=metadata)
        elif block_type == BlockType.POLICY_QA:
            chunks = chunk_policy_qa(text=text, metadata=metadata)
        elif block_type == BlockType.TABLE:
            table_data = parse_table_from_text(text)
            chunks = chunk_table(table_data, metadata) if table_data else []
            if not chunks:
                chunks = chunk_semantic_text(text=text, metadata=metadata)
        elif block_type == BlockType.EXAM_ITEM_MULTIMODAL:
            chunks = chunk_exam_item_multimodal(
                text=text,
                image_refs=list(metadata.get("image_refs") or []),
                metadata=metadata,
            )
        elif block_type == BlockType.POLICY_SECTION:
            chunks = chunk_policy_section(text=text, metadata=metadata)
        else:
            chunks = chunk_semantic_text(text=text, metadata=metadata)

        all_chunks.extend(_append_unique(all_chunks, chunks))
    return _normalize_chunks(all_chunks)


def _chunk_outline_sections(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]
    if not lines:
        return []

    sections: list[dict[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []
    module_keywords = (
        "行政职业能力测验",
        "申论",
        "常识判断",
        "言语理解与表达",
        "数量关系",
        "判断推理",
        "资料分析",
        "阅读理解能力",
        "综合分析能力",
        "提出和解决问题能力",
        "文字表达能力",
    )

    def flush() -> None:
        if not current_lines:
            return
        sections.append(
            {
                "heading": current_heading,
                "content": "\n".join(current_lines).strip(),
            }
        )

    for line in lines:
        is_heading = line in module_keywords or any(keyword in line for keyword in module_keywords)
        if is_heading:
            flush()
            current_heading = line
            current_lines = [line]
        else:
            current_lines.append(line)

    flush()
    if not sections:
        sections = [{"heading": "", "content": text}]

    chunks: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        heading = str(section.get("heading") or "").strip()
        content = str(section.get("content") or "").strip()
        if not content:
            continue
        chunk = _build_chunk(
            chunk_type=BlockType.POLICY_SECTION,
            metadata=metadata,
            content=content,
            question="",
            answer="",
            page_start=int(metadata.get("page_start", 0) or 0),
            page_end=int(metadata.get("page_end", 0) or 0),
            section_path=list(metadata.get("section_path") or []),
            title=heading or None,
            retrieval_queries=_build_retrieval_queries(heading or content, metadata),
            evidence_refs=list(metadata.get("evidence_refs") or []),
            extra={
                "heading": heading,
                "clause_id": None,
            },
        )
        chunk["chunk_index"] = index
        chunk["heading"] = heading
        if chunk_citation_guard(chunk) and chunk_noise_guard(chunk):
            chunks.append(chunk)
    return chunks


def _chunk_major_catalog_sections(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]
    if not lines:
        return []

    chunks: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if ":" not in line and "：" not in line:
            continue
        key, value = re.split(r"[:：]", line, maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key and not value:
            continue
        content = line.strip()
        chunk = _build_chunk(
            chunk_type=BlockType.POLICY_SECTION,
            metadata=metadata,
            content=content,
            question="",
            answer="",
            page_start=int(metadata.get("page_start", 0) or 0),
            page_end=int(metadata.get("page_end", 0) or 0),
            section_path=list(metadata.get("section_path") or []),
            title=key or None,
            retrieval_queries=_build_retrieval_queries(content, metadata),
            evidence_refs=list(metadata.get("evidence_refs") or []),
            extra={
                "heading": key,
                "clause_id": key or None,
            },
        )
        chunk["chunk_index"] = index
        chunk["heading"] = key
        chunk["clause_id"] = key or None
        if chunk_citation_guard(chunk) and chunk_noise_guard(chunk):
            chunks.append(chunk)
    return chunks


def classify_block_skill(text: str, metadata: dict[str, Any]) -> str:
    return classify_content_block(text, metadata).value


def extract_policy_qa_skill(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return chunk_policy_qa(text, metadata)


def extract_table_skill(table_data: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return chunk_table(table_data, metadata)


def extract_exam_item_skill(
    text: str,
    image_refs: list[str],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return chunk_exam_item_multimodal(text, image_refs, metadata)


def build_policy_section_chunks_skill(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return chunk_policy_section(text, metadata)


def chunk_quality_guard_skill(chunks: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for chunk in chunks:
        chunk_type = str(chunk.get("chunk_type") or "")
        if chunk_type == BlockType.POLICY_QA.value and not qa_pair_guard(chunk):
            warnings.append(f"qa_pair_guard failed for {chunk.get('chunk_id')}")
        if not chunk_noise_guard(chunk):
            warnings.append(f"chunk_noise_guard failed for {chunk.get('chunk_id')}")
        if chunk_type == BlockType.TABLE.value and not table_guard(chunk):
            warnings.append(f"table_guard failed for {chunk.get('chunk_id')}")
        if chunk_type == BlockType.EXAM_ITEM_MULTIMODAL.value and not exam_item_guard(chunk):
            warnings.append(f"exam_item_guard failed for {chunk.get('chunk_id')}")
        if not chunk_citation_guard(chunk):
            warnings.append(f"chunk_citation_guard failed for {chunk.get('chunk_id')}")
        if chunk_type == BlockType.POLICY_QA.value and not no_split_question_answer_guard(chunk):
            warnings.append(f"no_split_question_answer_guard failed for {chunk.get('chunk_id')}")
    return warnings


def _build_chunk(
    *,
    chunk_type: BlockType,
    metadata: dict[str, Any],
    content: str,
    question: str,
    answer: str,
    page_start: int,
    page_end: int,
    section_path: list[str],
    title: str | None,
    retrieval_queries: list[str],
    evidence_refs: list[dict[str, Any]],
    extra: dict[str, Any],
) -> dict[str, Any]:
    source_file = str(metadata.get("source_file", ""))
    source_category = str(metadata.get("source_category", "official") or "official")
    doc_type = str(metadata.get("doc_type", ""))
    chunk_id = str(extra.get("chunk_id") or uuid.uuid4().hex)
    chunk = {
        "chunk_id": chunk_id,
        "chunk_type": chunk_type.value,
        "doc_type": doc_type,
        "source_file": source_file,
        "source_category": source_category,
        "title": title,
        "section_path": section_path,
        "content": content,
        "page_start": page_start,
        "page_end": page_end,
        "bbox": list(metadata.get("bbox") or []),
        "metadata": {
            **dict(metadata),
            **extra,
            "chunk_type": chunk_type.value,
            "source_category": source_category,
            "section_path": section_path,
            "retrieval_queries": retrieval_queries,
            "evidence_refs": evidence_refs,
        },
        "retrieval_queries": retrieval_queries,
        "evidence_refs": evidence_refs,
    }
    if question:
        chunk["question"] = question
    if answer:
        chunk["answer"] = answer
    return chunk


def _build_retrieval_queries(text: str, metadata: dict[str, Any]) -> list[str]:
    queries = [
        normalize_text(text)[:120],
        str(metadata.get("doc_title") or metadata.get("title") or "").strip(),
        " > ".join(
            str(item).strip()
            for item in (metadata.get("section_path") or [])
            if str(item).strip()
        ),
    ]
    deduped: list[str] = []
    for query in queries:
        if query and query not in deduped:
            deduped.append(query)
    return deduped


def _extract_first_question(text: str) -> str:
    match = re.search(r"(?:问[:：]|问题[:：]|Q[:：])\s*(.+)", text)
    if match:
        return match.group(1).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else text.strip()


def _extract_first_answer(text: str) -> str:
    match = re.search(r"(?:答[:：]|回答[:：]|A[:：])\s*(.+)", text)
    if match:
        return match.group(1).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[1] if len(lines) > 1 else ""


def _extract_single_qa_pair(text: str, metadata: dict[str, Any]) -> dict[str, str] | None:
    normalized = normalize_text(text)
    if not normalized:
        return None

    question_title = str(metadata.get("doc_title") or "").strip()
    question_title = re.sub(r"^(?:技术问答|考务问答|政策问答)", "", question_title).strip()
    question_title = question_title.strip("？?")

    question_mark = normalized.find("？")
    if question_mark < 0:
        question_mark = normalized.find("?")
    if question_mark < 0:
        if not question_title:
            return None
        question = question_title
        answer = normalized
    else:
        question = question_title or normalized[: question_mark + 1].strip()
        if not question.endswith(("？", "?")):
            question = f"{question}？"
        answer = normalized[question_mark + 1 :].strip()

    answer = re.sub(r"^[:：\s]*", "", answer)
    answer = re.sub(r"^发布日期[:：]?\s*\d{4}-\d{2}-\d{2}\s*", "", answer)
    answer = re.sub(r"^(?:技术问答|考务问答|政策问答)\s*", "", answer)
    if question_title:
        answer = re.sub(rf"^{re.escape(question_title)}\s*", "", answer)
    answer = re.sub(r"(?:首页|返回顶部|咨询电话|版权所有|网站所有|个人中心)\s*$", "", answer)
    answer = normalize_text(answer).strip()
    if not answer:
        return None

    return {
        "question": question,
        "answer": answer,
        "content": f"问：{question}\n答：{answer}".strip(),
    }


def _parse_exam_item(text: str) -> tuple[str, dict[str, str], str | None, str | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", {}, None, None

    stem_lines: list[str] = []
    options: dict[str, str] = {}
    answer: str | None = None
    explanation: str | None = None
    current = "stem"
    current_option_key: str | None = None

    for line in lines:
        if re.match(r"^[A-D][\.、\)]\s*", line):
            current = "options"
            current_option_key = line[0]
            options[current_option_key] = re.sub(r"^[A-D][\.、\)]\s*", "", line).strip()
            continue
        if re.match(r"^(?:答案|参考答案)[:：]", line):
            answer = re.sub(r"^(?:答案|参考答案)[:：]\s*", "", line).strip()
            current = "answer"
            continue
        if re.match(r"^(?:解析|说明)[:：]", line):
            explanation = re.sub(r"^(?:解析|说明)[:：]\s*", "", line).strip()
            current = "explanation"
            continue

        if current == "stem":
            stem_lines.append(line)
        elif current == "options" and current_option_key:
            options[current_option_key] = f"{options[current_option_key]} {line}".strip()
        elif current == "answer":
            answer = f"{answer or ''} {line}".strip()
        elif current == "explanation":
            explanation = f"{explanation or ''} {line}".strip()

    stem = " ".join(stem_lines).strip()
    return stem, options, answer, explanation


def _detect_clause_id(text: str) -> str | None:
    match = re.search(r"(第[一二三四五六七八九十百千0-9]+[条章节篇部分])", text)
    if match:
        return match.group(1)
    return None


def _append_unique(
    existing: list[dict[str, Any]],
    new_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {
        make_content_hash(
            chunk.get("chunk_type"),
            chunk.get("source_file"),
            chunk.get("page_start"),
            chunk.get("page_end"),
            normalize_text(str(chunk.get("content", ""))),
            chunk.get("metadata", {}).get("table_id"),
            chunk.get("metadata", {}).get("image_id"),
            chunk.get("metadata", {}).get("row_key"),
        )
        for chunk in existing
    }
    deduped: list[dict[str, Any]] = []
    for chunk in new_chunks:
        signature = make_content_hash(
            chunk.get("chunk_type"),
            chunk.get("source_file"),
            chunk.get("page_start"),
            chunk.get("page_end"),
            normalize_text(str(chunk.get("content", ""))),
            chunk.get("metadata", {}).get("table_id"),
            chunk.get("metadata", {}).get("image_id"),
            chunk.get("metadata", {}).get("row_key"),
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(chunk)
    return deduped


def _normalize_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        signature = make_content_hash(
            chunk.get("chunk_type"),
            chunk.get("source_file"),
            chunk.get("page_start"),
            chunk.get("page_end"),
            normalize_text(str(chunk.get("content", ""))),
            chunk.get("metadata", {}).get("table_id"),
            chunk.get("metadata", {}).get("image_id"),
            chunk.get("metadata", {}).get("row_key"),
        )
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append(chunk)
    return normalized


def _normalize_columns(columns: list[Any]) -> list[str]:
    return [str(column).strip() for column in columns if str(column).strip()]


def _normalize_rows(rows: list[Any]) -> list[list[str]]:
    normalized: list[list[str]] = []
    for row in rows:
        values = [str(cell).strip() for cell in (row or []) if str(cell).strip()]
        if values:
            normalized.append(values)
    return normalized
