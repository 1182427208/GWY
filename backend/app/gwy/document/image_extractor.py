from __future__ import annotations

import re
import hashlib
import uuid
import tempfile
from pathlib import Path
from typing import Any

from app.gwy.llm.multimodal_service import MultimodalSummaryService


def extract_pdf_image_assets(
    file_path: str,
    *,
    layout_pages: list[dict[str, Any]] | None = None,
    summary_service: MultimodalSummaryService | None = None,
) -> list[dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("PyMuPDF is required for image extraction.") from exc

    summary_service = summary_service or MultimodalSummaryService()
    document = fitz.open(str(path))
    try:
        image_root = _asset_root(path)
        image_root.mkdir(parents=True, exist_ok=True)

        assets: list[dict[str, Any]] = []
        for page_index, page in enumerate(document, start=1):
            page_blocks = _page_blocks(layout_pages, page_index)
            try:
                images = page.get_images(full=True)
            except Exception:  # pragma: no cover - defensive
                images = []

            seen_rects: set[tuple[float, float, float, float]] = set()
            for image_index, image in enumerate(images, start=1):
                xref = int(image[0])
                try:
                    rects = page.get_image_rects(xref)
                except Exception:  # pragma: no cover - defensive
                    rects = []
                for rect in rects:
                    bbox = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
                    bbox_key = tuple(round(value, 2) for value in bbox)
                    if bbox_key in seen_rects:
                        continue
                    seen_rects.add(bbox_key)

                    image_id = uuid.uuid4().hex
                    image_path = image_root / f"page_{page_index}_img_{image_index}.png"
                    _write_image_asset(page=page, bbox=bbox, xref=xref, output_path=image_path)
                    nearby_text = _collect_nearby_text(page_blocks, bbox)
                    summary_payload = summary_service.summarize_image(
                        image_path=str(image_path),
                        nearby_text=nearby_text,
                        source_file=str(path),
                        page=page_index,
                        bbox=bbox,
                    )
                    assets.append(
                        {
                            "image_id": image_id,
                            "asset_type": "image",
                            "source_file": str(path),
                            "page": page_index,
                            "bbox": bbox,
                            "image_path": str(image_path),
                            "nearby_text": nearby_text,
                            "summary": str(summary_payload.get("summary", "")),
                            "ocr_text": str(summary_payload.get("ocr_text", "")),
                            "extraction_status": str(
                                summary_payload.get("extraction_status", "pending_multimodal_summary")
                            ),
                            "linked_chunk_ids": [],
                        }
                    )
        return assets
    finally:
        document.close()


def image_assets_to_chunks(image_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for asset in image_assets:
        summary = str(asset.get("summary", "")).strip()
        nearby_text = str(asset.get("nearby_text", "")).strip()
        ocr_text = str(asset.get("ocr_text", "")).strip()
        source_file = str(asset.get("source_file", ""))
        page = int(asset.get("page", 0) or 0)
        bbox = list(asset.get("bbox") or [])
        content_parts = [
            f"图片来源：{Path(source_file).name or source_file} 第 {page} 页",
        ]
        if nearby_text:
            content_parts.append(f"图片附近文本：{nearby_text}")
        if summary:
            content_parts.append(f"图片内容摘要：{summary}")
        if ocr_text and ocr_text != summary:
            content_parts.append(f"图片中文字：{ocr_text}")
        chunks.append(
            {
                "chunk_id": uuid.uuid4().hex,
                "content": "\n".join(content_parts).strip(),
                "question": "",
                "section": "",
                "chunk_type": "image_summary",
                "asset_type": "image",
                "image_id": asset.get("image_id"),
                "image_path": asset.get("image_path"),
                "page_start": page,
                "page_end": page,
                "bbox_list": [bbox] if bbox else [],
                "metadata": {
                    "source_file": source_file,
                    "image_id": asset.get("image_id"),
                    "image_path": asset.get("image_path"),
                    "page": page,
                    "bbox": bbox,
                    "asset_type": "image",
                    "extraction_status": asset.get("extraction_status"),
                },
            }
        )
    return chunks


def _asset_root(path: Path) -> Path:
    temp_root = Path(tempfile.gettempdir()) / "gwy_pilot_artifacts"
    return temp_root / "assets" / "images" / _safe_stem(path)


def _page_blocks(
    layout_pages: list[dict[str, Any]] | None,
    page_number: int,
) -> list[dict[str, Any]]:
    if not layout_pages:
        return []
    for page in layout_pages:
        if int(page.get("page", 0) or 0) == page_number:
            return list(page.get("blocks") or [])
    return []


def _write_image_asset(
    *,
    page: Any,
    bbox: list[float],
    xref: int,
    output_path: Path,
) -> None:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("PyMuPDF is required for image extraction.") from exc

    try:
        image = page.parent.extract_image(xref)
        image_bytes = image.get("image") if isinstance(image, dict) else None
        image_ext = str(image.get("ext", "")).lower() if isinstance(image, dict) else ""
        if image_bytes and image_ext in {"png", "webp"}:
            output_path.write_bytes(image_bytes)
            return
    except Exception:  # pragma: no cover - fallback
        pass

    rect = fitz.Rect(*bbox)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
    pixmap.save(str(output_path))


def _collect_nearby_text(
    blocks: list[dict[str, Any]],
    bbox: list[float],
) -> str:
    if not blocks:
        return ""
    nearby: list[str] = []
    for block in blocks:
        if str(block.get("block_type")) not in {"text", "title"}:
            continue
        block_bbox = block.get("bbox") or []
        if not isinstance(block_bbox, list) or len(block_bbox) != 4:
            continue
        if _bbox_distance(block_bbox, bbox) <= 220:
            text = str(block.get("text", "")).strip()
            if text:
                nearby.append(text)
    return "\n".join(nearby[:3]).strip()


def _bbox_distance(a: list[float], b: list[float]) -> float:
    ax = (float(a[0]) + float(a[2])) / 2
    ay = (float(a[1]) + float(a[3])) / 2
    bx = (float(b[0]) + float(b[2])) / 2
    by = (float(b[1]) + float(b[3])) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _safe_stem(path: Path) -> str:
    stem = path.stem
    ascii_stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._")
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    if ascii_stem:
        return f"{ascii_stem}_{digest}"
    return f"source_{digest}"

