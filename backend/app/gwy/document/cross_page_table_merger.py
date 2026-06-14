from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def merge_cross_page_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tables:
        return []

    ordered = sorted(
        [dict(table) for table in tables],
        key=lambda item: (
            int(item.get("page_start", 0) or 0),
            float((item.get("bbox") or [0, 0, 0, 0])[1]),
        ),
    )
    merged: list[dict[str, Any]] = []
    current = dict(ordered[0])

    for table in ordered[1:]:
        if _can_merge(current, table):
            current = _merge_pair(current, table)
            continue
        merged.append(current)
        current = dict(table)

    merged.append(current)
    return merged


def _can_merge(current: dict[str, Any], candidate: dict[str, Any]) -> bool:
    current_end = int(current.get("page_end", current.get("page_start", 0)) or 0)
    candidate_start = int(candidate.get("page_start", 0) or 0)
    if candidate_start != current_end + 1:
        return False

    current_columns = list(current.get("columns") or [])
    candidate_columns = list(candidate.get("columns") or [])
    if not current_columns or not candidate_columns:
        return False
    if len(current_columns) != len(candidate_columns):
        if abs(len(current_columns) - len(candidate_columns)) > 1:
            return False

    if _jaccard_similarity(current_columns, candidate_columns) < 0.7:
        return False

    current_bbox = current.get("bbox") or []
    candidate_bbox = candidate.get("bbox") or []
    if len(current_bbox) == 4 and len(candidate_bbox) == 4:
        horizontal_distance = abs(float(current_bbox[0]) - float(candidate_bbox[0]))
        if horizontal_distance > 120:
            return False
    if candidate.get("has_new_title"):
        return False

    candidate_rows = list(candidate.get("rows") or [])
    if candidate_rows:
        first_row = candidate_rows[0]
        if _looks_like_header(first_row, candidate_columns):
            return False
    return True


def _merge_pair(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    merged["page_end"] = int(candidate.get("page_end", candidate.get("page_start", 0)) or 0)
    merged["is_cross_page"] = True
    source_pages = list(_ensure_list(current.get("source_pages"))) + list(
        _ensure_list(candidate.get("source_pages"))
    )
    merged["source_pages"] = sorted({int(page) for page in source_pages if int(page) > 0})
    merged["rows"] = [*list(current.get("rows") or []), *list(candidate.get("rows") or [])]
    merged["markdown_content"] = _rows_to_markdown(
        merged.get("columns") or [],
        merged.get("rows") or [],
    )
    merged["linked_chunk_ids"] = list(
        dict.fromkeys(
            [*list(current.get("linked_chunk_ids") or []), *list(candidate.get("linked_chunk_ids") or [])]
        )
    )
    return merged


def _jaccard_similarity(left: Iterable[Any], right: Iterable[Any]) -> float:
    left_tokens = {_normalize_token(str(item)) for item in left if str(item).strip()}
    right_tokens = {_normalize_token(str(item)) for item in right if str(item).strip()}
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _looks_like_header(row: Any, columns: list[Any]) -> bool:
    values = [str(cell).strip() for cell in (row or []) if str(cell).strip()]
    if not values:
        return False
    if len(values) != len(columns):
        return False
    return _jaccard_similarity(values, columns) >= 0.75


def _rows_to_markdown(columns: list[Any], rows: list[Any]) -> str:
    normalized_columns = [str(col).strip() or f"col_{index + 1}" for index, col in enumerate(columns)]
    if not normalized_columns and rows:
        first_row = rows[0]
        normalized_columns = [f"col_{index + 1}" for index, _ in enumerate(first_row)]
    if not normalized_columns:
        return ""

    md_rows = ["| " + " | ".join(normalized_columns) + " |"]
    md_rows.append("| " + " | ".join(["---"] * len(normalized_columns)) + " |")
    for row in rows:
        values = [str(cell).strip() for cell in (row or [])]
        if len(values) < len(normalized_columns):
            values.extend([""] * (len(normalized_columns) - len(values)))
        md_rows.append("| " + " | ".join(values[: len(normalized_columns)]) + " |")
    return "\n".join(md_rows)


def _normalize_token(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]
