from __future__ import annotations

import re
import hashlib
import uuid
import tempfile
from pathlib import Path
from typing import Any

from app.gwy.document_processing.extractors import (
    has_question_answer_structure,
    normalize_text,
    parse_table_from_text,
    table_rows_to_markdown,
)
from app.gwy.document_processing.router import BlockType, classify_content_block
from app.gwy.document.cross_page_table_merger import merge_cross_page_tables


def extract_pdf_tables(
    file_path: str,
    *,
    layout_pages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    try:
        import fitz  # type: ignore[import-not-found]
        import pdfplumber  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("PyMuPDF and pdfplumber are required for table extraction.") from exc

    table_root = _asset_root(path)
    table_root.mkdir(parents=True, exist_ok=True)

    raw_tables: list[dict[str, Any]] = []
    table_rows: list[dict[str, Any]] = []
    table_chunks: list[dict[str, Any]] = []

    document = fitz.open(str(path))
    plumber = pdfplumber.open(str(path))
    try:
        for page_index, plumber_page in enumerate(plumber.pages, start=1):
            page = document[page_index - 1]
            page_tables = _extract_page_tables(
                page=page,
                page_index=page_index,
                plumber_page=plumber_page,
                layout_pages=layout_pages,
                table_root=table_root,
                source_file=str(path),
            )
            for table in page_tables:
                raw_tables.append(table)

        merged_tables = merge_cross_page_tables(raw_tables)
        for table in merged_tables:
            table_rows.extend(_build_table_rows(table))
            table_chunks.extend(_build_table_chunks(table))

        return {
            "tables": merged_tables,
            "rows": table_rows,
            "chunks": table_chunks,
        }
    finally:
        plumber.close()
        document.close()


def _extract_page_tables(
    *,
    page: Any,
    page_index: int,
    plumber_page: Any,
    layout_pages: list[dict[str, Any]] | None,
    table_root: Path,
    source_file: str,
) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    try:
        page_tables = plumber_page.find_tables()
    except Exception:  # pragma: no cover - defensive
        page_tables = []

    for table_index, table in enumerate(page_tables, start=1):
        bbox = getattr(table, "bbox", None)
        rows = []
        try:
            rows = table.extract() or []
        except Exception:  # pragma: no cover - defensive
            rows = []

        columns = _derive_columns(rows)
        table_id = uuid.uuid4().hex
        table_image_path = _render_table_image(
            page=page,
            bbox=bbox,
            table_root=table_root,
            page_index=page_index,
            table_index=table_index,
        )
        context = _collect_table_context(layout_pages, page_index, bbox)
        markdown_content = _rows_to_markdown(columns, rows)
        if not _is_real_table_candidate(
            context=context,
            markdown_content=markdown_content,
            columns=columns,
            rows=rows,
            source_file=source_file,
        ):
            continue
        extraction_status = "success" if rows else "partial"
        tables.append(
            {
                "table_id": table_id,
                "source_file": source_file,
                "page_start": page_index,
                "page_end": page_index,
                "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])] if bbox else [],
                "columns": columns,
                "rows": rows,
                "markdown_content": markdown_content,
                "table_image_path": str(table_image_path),
                "extraction_status": extraction_status,
                "is_cross_page": False,
                "source_pages": [page_index],
                "linked_chunk_ids": [],
                "context": context,
                "has_new_title": bool(context and _looks_like_title(context)),
            }
        )
    return tables


def _build_table_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(_data_rows(table)):
        row_values = [str(cell).strip() for cell in (row or [])]
        row_text = _row_to_text(table.get("columns") or [], row_values)
        if not _should_keep_table_row(table.get("columns") or [], row_values, row_text):
            continue
        row_json = {
            str(column or f"col_{index + 1}"): row_values[index] if index < len(row_values) else ""
            for index, column in enumerate(table.get("columns") or [])
        }
        rows.append(
            {
                "id": uuid.uuid4().hex,
                "table_id": table.get("table_id"),
                "row_index": row_index,
                "row_text": row_text,
                "row_json": row_json,
                "page": int(table.get("page_start", 0) or 0),
                "created_at": "",
            }
        )
    return rows


def _build_table_chunks(table: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    summary_content = _build_table_summary_content(table)
    chunks.append(
        {
            "chunk_id": uuid.uuid4().hex,
            "content": summary_content,
            "question": "",
            "section": str(table.get("context", ""))[:120],
            "chunk_type": "table_summary",
            "asset_type": "table",
            "table_id": table.get("table_id"),
            "table_image_path": table.get("table_image_path"),
            "page_start": table.get("page_start"),
            "page_end": table.get("page_end"),
            "bbox_list": [table.get("bbox")] if table.get("bbox") else [],
            "metadata": {
                "source_file": table.get("source_file"),
                "table_id": table.get("table_id"),
                "table_image_path": table.get("table_image_path"),
                "page_start": table.get("page_start"),
                "page_end": table.get("page_end"),
                "asset_type": "table",
                "extraction_status": table.get("extraction_status"),
                "is_cross_page": table.get("is_cross_page", False),
                "source_pages": table.get("source_pages", []),
                "columns": table.get("columns", []),
            },
        }
    )

    for row in _build_table_rows(table):
        chunks.append(
            {
                "chunk_id": uuid.uuid4().hex,
                "content": row["row_text"],
                "question": "",
                "section": str(table.get("context", ""))[:120],
                "chunk_type": "table_row",
                "asset_type": "table",
                "table_id": table.get("table_id"),
                "row_id": row["id"],
                "table_image_path": table.get("table_image_path"),
                "page_start": table.get("page_start"),
                "page_end": table.get("page_end"),
                "bbox_list": [table.get("bbox")] if table.get("bbox") else [],
                "metadata": {
                    "source_file": table.get("source_file"),
                    "table_id": table.get("table_id"),
                    "row_id": row["id"],
                    "table_image_path": table.get("table_image_path"),
                    "page_start": table.get("page_start"),
                    "page_end": table.get("page_end"),
                    "asset_type": "table",
                    "columns": table.get("columns", []),
                    "row_json": row["row_json"],
                    "is_cross_page": table.get("is_cross_page", False),
                    "source_pages": table.get("source_pages", []),
                    "extraction_status": table.get("extraction_status"),
                },
            }
        )
    return chunks


def _render_table_image(
    *,
    page: Any,
    bbox: list[float] | tuple[float, float, float, float] | None,
    table_root: Path,
    page_index: int,
    table_index: int,
) -> Path:
    output_path = table_root / f"table_{page_index}_{table_index}.png"
    try:
        import fitz  # type: ignore[import-not-found]

        if bbox:
            rect = fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
            pixmap.save(str(output_path))
        else:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(str(output_path))
    except Exception:  # pragma: no cover - best effort
        output_path.write_bytes(b"")
    return output_path


def _collect_table_context(
    layout_pages: list[dict[str, Any]] | None,
    page_index: int,
    bbox: Any,
) -> str:
    if not layout_pages:
        return ""
    page_blocks = []
    for page in layout_pages:
        if int(page.get("page", 0) or 0) == page_index:
            page_blocks = list(page.get("blocks") or [])
            break
    if not page_blocks:
        return ""

    top_edge = float(bbox[1]) if bbox and len(bbox) == 4 else 0.0
    candidates: list[str] = []
    for block in page_blocks:
        if str(block.get("block_type")) not in {"title", "text"}:
            continue
        block_bbox = block.get("bbox") or []
        if not isinstance(block_bbox, list) or len(block_bbox) != 4:
            continue
        if float(block_bbox[3]) <= top_edge + 40:
            text = str(block.get("text", "")).strip()
            if text:
                candidates.append(text)
    if not candidates:
        return ""
    return candidates[-1]


def _derive_columns(rows: list[list[Any]]) -> list[str]:
    if not rows:
        return []
    first_row = [str(cell).strip() for cell in rows[0] if str(cell).strip()]
    if first_row:
        return first_row
    width = max((len(row) for row in rows), default=0)
    return [f"col_{index + 1}" for index in range(width)]


def _rows_to_markdown(columns: list[str], rows: list[list[Any]]) -> str:
    if not columns and not rows:
        return ""
    if not columns:
        columns = [f"col_{index + 1}" for index in range(max((len(row) for row in rows), default=0))]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, separator]
    for row in _data_rows({"columns": columns, "rows": rows}):
        values = [str(cell).strip() for cell in (row or [])]
        if len(values) < len(columns):
            values.extend([""] * (len(columns) - len(values)))
        lines.append("| " + " | ".join(values[: len(columns)]) + " |")
    return "\n".join(lines)


def _row_to_text(columns: list[Any], row_values: list[str]) -> str:
    pairs: list[str] = []
    for index, column in enumerate(columns):
        value = row_values[index] if index < len(row_values) else ""
        pairs.append(f"{str(column).strip() or f'col_{index + 1}'}：{value}")
    return "；".join(pairs)


def _should_keep_table_row(
    columns: list[Any],
    row_values: list[str],
    row_text: str,
) -> bool:
    if len(columns) < 2:
        return False
    meaningful_columns = [
        str(column).strip()
        for column in columns
        if str(column).strip() and _normalize_token(str(column)) not in {"none", "null", "nan"}
    ]
    if len(meaningful_columns) < 2:
        return False
    normalized_values = [str(value).strip() for value in row_values if str(value).strip()]
    if not normalized_values:
        return False
    if all(_normalize_token(value) in {"none", "null"} for value in normalized_values):
        return False
    none_like_count = sum(1 for value in normalized_values if re.match(r"^(?:none|null)(?:[:：]|$)", value, re.IGNORECASE))
    if none_like_count >= max(1, len(normalized_values) // 2):
        return False
    if all(_normalize_token(value) in _navigation_tokens() for value in normalized_values):
        return False
    if _looks_like_noise_row(row_text):
        return False
    if any(
        _looks_like_noise_row(value)
        for value in normalized_values
        if value
    ):
        return False
    if len(normalized_values) < 2:
        return False
    if len(row_text.strip()) < 8:
        return False
    return True


def _looks_like_noise_row(row_text: str) -> bool:
    normalized = normalize_text(row_text)
    if not normalized:
        return True
    if any(
        marker in normalized
        for marker in (
            "版权所有",
            "网站所有",
            "国家公务员局",
            "中央机关及其直属机构2026年度考试录用公务员专题",
            "返回顶部",
            "咨询电话",
        )
    ):
        return True
    if ">" in normalized and normalized.count(">") >= 1:
        return True
    if re.search(r"首页.*招考公告.*政策法规.*常见问题.*相关下载.*公告公示.*个人中心", normalized):
        return True
    if re.fullmatch(r"(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心)(?:\s*(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心))+",
                    normalized):
        return True
    if normalized.endswith(("：", ":", "；", ";")) and len(normalized) <= 40:
        return True
    if re.match(r"^(?:第[一二三四五六七八九十百千0-9]+[章节条篇部分]|[一二三四五六七八九十百千0-9]+[、.．)]|\([一二三四五六七八九十百千0-9]+\)|（[一二三四五六七八九十百千0-9]+）)", normalized):
        return True
    if "None：None" in normalized or "None" == normalized:
        return True
    return False


def _navigation_tokens() -> set[str]:
    return {
        _normalize_token(value)
        for value in (
            "首页",
            "招考公告",
            "政策法规",
            "常见问题",
            "相关下载",
            "公告公示",
            "个人中心",
            "返回顶部",
            "咨询电话",
        )
    }


def _looks_like_title(text: str) -> bool:
    if len(text) > 80:
        return False
    return bool(re.search(r"(表|目录|大纲|公告|指南|问答|章节)", text))


def _asset_root(path: Path) -> Path:
    temp_root = Path(tempfile.gettempdir()) / "gwy_pilot_artifacts"
    return temp_root / "assets" / "tables" / _safe_stem(path)


def _safe_stem(path: Path) -> str:
    stem = path.stem
    ascii_stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._")
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    if ascii_stem:
        return f"{ascii_stem}_{digest}"
    return f"source_{digest}"


def _data_rows(table: dict[str, Any]) -> list[list[Any]]:
    rows = [list(row or []) for row in (table.get("rows") or [])]
    if not rows:
        return []

    columns = [str(column).strip() for column in (table.get("columns") or [])]
    first_row = [str(cell).strip() for cell in rows[0]]
    if columns and _row_matches_columns(first_row, columns):
        return rows[1:]
    return rows


def _row_matches_columns(row: list[str], columns: list[str]) -> bool:
    if len(row) != len(columns):
        return False
    normalized_row = [_normalize_token(value) for value in row]
    normalized_columns = [_normalize_token(value) for value in columns]
    return normalized_row == normalized_columns


def _normalize_token(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _build_table_summary_content(table: dict[str, Any]) -> str:
    context = str(table.get("context", "")).strip()
    columns = [str(col).strip() for col in (table.get("columns") or []) if str(col).strip()]
    markdown = str(table.get("markdown_content", "")).strip()
    parts = []
    if context:
        parts.append(f"表格上下文：{context}")
    if columns:
        parts.append(f"表头列：{'、'.join(columns)}")
    if markdown:
        parts.append(f"表格结构：\n{markdown}")
    if not parts:
        parts.append("表格摘要：当前仅检测到结构化表格。")
    return "\n\n".join(parts)


def _is_real_table_candidate(
    *,
    context: str,
    markdown_content: str,
    columns: list[str],
    rows: list[list[Any]],
    source_file: str,
) -> bool:
    if len(columns) < 2 or len(rows) < 1:
        return False
    preview_text = normalize_text("\n".join([context, markdown_content]))
    if not preview_text:
        return False
    if _looks_like_navigation_table(columns, rows, preview_text):
        return False
    if has_question_answer_structure(preview_text):
        return False
    if re.search(r"(?:问[:：]|问题[:：]|答[:：]|回答[:：]|Q[:：]|A[:：])", preview_text):
        return False

    route = classify_content_block(
        preview_text,
        {
            "source_file": source_file,
            "source_category": "official",
            "doc_group": "table_candidate",
            "columns": columns,
            "rows": rows,
        },
    )
    if route not in {BlockType.TABLE, BlockType.TABLE_ROW, BlockType.POLICY_SECTION}:
        return False

    parsed = parse_table_from_text(preview_text)
    if parsed is None and len(rows) < 2:
        return False
    return True


def _looks_like_navigation_table(
    columns: list[str],
    rows: list[list[Any]],
    preview_text: str,
) -> bool:
    normalized_preview = normalize_text(preview_text)
    nav_markers = (
        "首页",
        "招考公告",
        "政策法规",
        "常见问题",
        "相关下载",
        "公告公示",
        "个人中心",
        "返回顶部",
        "咨询电话",
        "版权所有",
        "网站所有",
    )
    if any(
        marker in normalized_preview
        for marker in (
            "首页 > 招考公告 > 招考公告",
            "首页招考公告政策法规常见问题相关下载公告公示个人中心",
            "返回顶部咨询电话",
        )
    ):
        return True

    normalized_columns = [normalize_text(column) for column in columns]
    meaningful_columns = [
        column
        for column in normalized_columns
        if column and _normalize_token(column) not in {"none", "null", "nan"}
    ]
    if len(meaningful_columns) < 2:
        return True
    nav_column_count = sum(
        1
        for column in normalized_columns
        if any(marker in column for marker in nav_markers)
    )
    if nav_column_count >= max(1, len(normalized_columns) - 1):
        return True

    if normalized_columns and all(
        any(marker in column for marker in nav_markers) for column in normalized_columns
    ):
        return True

    row_texts = [
        normalize_text(_row_to_text(columns, [str(cell) for cell in row]))
        for row in rows[:3]
    ]
    if row_texts and all(
        (
            any(marker in row_text for marker in nav_markers)
            or not _row_text_has_meaningful_content(row_text)
        )
        for row_text in row_texts
    ):
        return True

    return False


def _row_text_has_meaningful_content(row_text: str) -> bool:
    normalized = normalize_text(row_text)
    if not normalized:
        return False
    if len(normalized) < 20 and not any(ch.isdigit() for ch in normalized):
        return False
    if normalized.count("None") >= 1:
        return False
    return True
