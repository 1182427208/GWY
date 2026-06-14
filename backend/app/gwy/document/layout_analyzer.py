from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any


HEADER_FOOTER_RATIO = 0.12
FOOTER_RATIO = 0.88


def analyze_pdf_layout(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("PyMuPDF is required for layout analysis.") from exc

    pdfplumber_module: Any | None = None
    try:  # pragma: no cover - optional dependency
        import pdfplumber as _pdfplumber  # type: ignore[import-not-found]

        pdfplumber_module = _pdfplumber
    except Exception:  # pragma: no cover - optional dependency
        pdfplumber_module = None

    document = fitz.open(str(path))
    plumber = pdfplumber_module.open(str(path)) if pdfplumber_module else None
    try:
        pages: list[dict[str, Any]] = []
        all_blocks: list[dict[str, Any]] = []
        for page_index, page in enumerate(document, start=1):
            page_height = float(page.rect.height or 1.0)
            page_width = float(page.rect.width or 1.0)
            plumber_page = None
            if plumber and page_index - 1 < len(plumber.pages):
                plumber_page = plumber.pages[page_index - 1]

            table_bboxes = _detect_table_bboxes(plumber_page)
            text_blocks = _extract_text_blocks(
                page=page,
                page_number=page_index,
                page_height=page_height,
                table_bboxes=table_bboxes,
            )
            image_blocks = _extract_image_blocks(
                page=page,
                page_number=page_index,
            )
            table_blocks = _extract_table_blocks(
                page_number=page_index,
                table_bboxes=table_bboxes,
                plumber_page=plumber_page,
            )

            blocks = sorted(
                [*text_blocks, *image_blocks, *table_blocks],
                key=lambda item: (
                    float((item.get("bbox") or [0, 0, 0, 0])[1]),
                    float((item.get("bbox") or [0, 0, 0, 0])[0]),
                ),
            )
            pages.append(
                {
                    "page": page_index,
                    "width": page_width,
                    "height": page_height,
                    "blocks": blocks,
                }
            )
            all_blocks.extend(blocks)

        return {
            "source_file": str(path),
            "page_count": len(pages),
            "pages": pages,
            "blocks": all_blocks,
        }
    finally:
        if plumber is not None:
            plumber.close()
        document.close()


def _extract_text_blocks(
    *,
    page: Any,
    page_number: int,
    page_height: float,
    table_bboxes: list[list[float]],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    try:
        raw_blocks = page.get_text("blocks", sort=True)
    except Exception:  # pragma: no cover - defensive
        raw_blocks = []

    for raw_block in raw_blocks:
        if not raw_block:
            continue
        bbox = [
            float(raw_block[0]),
            float(raw_block[1]),
            float(raw_block[2]),
            float(raw_block[3]),
        ]
        text = _normalize_text(str(raw_block[4] if len(raw_block) > 4 else ""))
        if not text:
            continue
        if _bbox_intersects_any(bbox, table_bboxes, min_ratio=0.35):
            continue

        block_type = "text"
        if bbox[1] <= page_height * HEADER_FOOTER_RATIO:
            block_type = "header"
        elif bbox[1] >= page_height * FOOTER_RATIO:
            block_type = "footer"
        elif _looks_like_title(text):
            block_type = "title"

        blocks.append(
            {
                "block_id": uuid.uuid4().hex,
                "block_type": block_type,
                "page": page_number,
                "bbox": bbox,
                "text": text,
                "image_path": "",
                "table_id": "",
                "confidence": _block_confidence(block_type),
            }
        )
    return blocks


def _extract_image_blocks(*, page: Any, page_number: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    seen_rects: set[tuple[float, float, float, float]] = set()
    try:
        images = page.get_images(full=True)
    except Exception:  # pragma: no cover - defensive
        images = []

    for image in images:
        try:
            xref = int(image[0])
            rects = page.get_image_rects(xref)
        except Exception:  # pragma: no cover - defensive
            rects = []
        for rect in rects:
            bbox = [
                float(rect.x0),
                float(rect.y0),
                float(rect.x1),
                float(rect.y1),
            ]
            bbox_key = tuple(round(value, 2) for value in bbox)
            if bbox_key in seen_rects:
                continue
            seen_rects.add(bbox_key)
            blocks.append(
                {
                    "block_id": uuid.uuid4().hex,
                    "block_type": "image",
                    "page": page_number,
                    "bbox": bbox,
                    "text": "",
                    "image_path": "",
                    "table_id": "",
                    "confidence": 0.8,
                }
            )
    return blocks


def _detect_table_bboxes(plumber_page: Any | None) -> list[list[float]]:
    if plumber_page is None:
        return []
    try:
        tables = plumber_page.find_tables()
    except Exception:  # pragma: no cover - defensive
        tables = []
    bboxes: list[list[float]] = []
    for table in tables:
        bbox = getattr(table, "bbox", None)
        if not bbox:
            continue
        bboxes.append([float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])])
    return bboxes


def _extract_table_blocks(
    *,
    page_number: int,
    table_bboxes: list[list[float]],
    plumber_page: Any | None,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if plumber_page is None:
        return blocks

    try:
        tables = plumber_page.find_tables()
    except Exception:  # pragma: no cover - defensive
        tables = []

    for table_index, table in enumerate(tables, start=1):
        bbox = getattr(table, "bbox", None)
        rows = []
        try:
            rows = table.extract() or []
        except Exception:  # pragma: no cover - defensive
            rows = []
        table_id = uuid.uuid4().hex
        if bbox:
            blocks.append(
                {
                    "block_id": uuid.uuid4().hex,
                    "block_type": "table",
                    "page": page_number,
                    "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                    "text": _table_preview(rows),
                    "image_path": "",
                    "table_id": table_id,
                    "confidence": 0.9 if rows else 0.7,
                    "row_count": len(rows),
                    "table_index": table_index,
                }
            )
    return blocks


def _table_preview(rows: list[list[Any]]) -> str:
    flattened: list[str] = []
    for row in rows[:3]:
        flattened.append(" | ".join(str(cell).strip() for cell in row if cell not in (None, "")))
    return "\n".join(flattened)


def _normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current).strip())
    return "\n".join(part for part in paragraphs if part).strip()


def _looks_like_title(text: str) -> bool:
    if len(text) > 60:
        return False
    title_patterns = (
        r"^第[一二三四五六七八九十0-9]+[章节篇部分条]?",
        r"^[一二三四五六七八九十0-9]+[、.．]",
        r"^[（(][一二三四五六七八九十0-9]+[)）]",
    )
    if any(re.match(pattern, text) for pattern in title_patterns):
        return True
    return bool(re.search(r"(考试大纲|招考简章|公告|政策|指南|问答)", text))


def _bbox_intersects_any(
    bbox: list[float],
    others: list[list[float]],
    *,
    min_ratio: float,
) -> bool:
    for other in others:
        if _bbox_overlap_ratio(bbox, other) >= min_ratio:
            return True
    return False


def _bbox_overlap_ratio(a: list[float], b: list[float]) -> float:
    x_left = max(a[0], b[0])
    y_top = max(a[1], b[1])
    x_right = min(a[2], b[2])
    y_bottom = min(a[3], b[3])
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0

    intersection = (x_right - x_left) * (y_bottom - y_top)
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    area_b = max((b[2] - b[0]) * (b[3] - b[1]), 1e-6)
    return intersection / min(area_a, area_b)


def _block_confidence(block_type: str) -> float:
    return {
        "title": 0.95,
        "text": 0.9,
        "header": 0.55,
        "footer": 0.55,
        "image": 0.8,
        "table": 0.9,
    }.get(block_type, 0.75)
