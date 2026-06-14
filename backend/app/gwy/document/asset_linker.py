from __future__ import annotations

from collections import defaultdict
from typing import Any


def link_assets_to_chunks(
    chunks: list[dict[str, Any]],
    *,
    layout_pages: list[dict[str, Any]],
    image_assets: list[dict[str, Any]] | None = None,
    table_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    image_assets = [dict(asset) for asset in (image_assets or [])]
    table_assets = [dict(asset) for asset in (table_assets or [])]

    page_blocks = _page_blocks_index(layout_pages)
    chunk_index: dict[str, dict[str, Any]] = {}
    chunks_with_assets: list[dict[str, Any]] = []

    for chunk in chunks:
        enriched = dict(chunk)
        enriched.setdefault("asset_type", "text")
        bbox_list = _collect_chunk_bbox_list(enriched, page_blocks)
        enriched["bbox_list"] = bbox_list
        metadata = dict(enriched.get("metadata") or {})
        metadata["bbox_list"] = bbox_list
        metadata.setdefault("asset_type", enriched.get("asset_type", "text"))
        enriched["metadata"] = metadata
        enriched.setdefault("linked_image_ids", [])
        enriched.setdefault("linked_table_ids", [])
        chunks_with_assets.append(enriched)
        chunk_index[str(enriched.get("chunk_id"))] = enriched

    for asset in image_assets:
        linked_chunk_ids = _link_asset_to_chunks(
            asset=asset,
            chunks=chunks_with_assets,
            page_blocks=page_blocks,
            asset_type="image",
        )
        asset["linked_chunk_ids"] = linked_chunk_ids
        asset["linked_count"] = len(linked_chunk_ids)

    for asset in table_assets:
        linked_chunk_ids = _link_asset_to_chunks(
            asset=asset,
            chunks=chunks_with_assets,
            page_blocks=page_blocks,
            asset_type="table",
        )
        asset["linked_chunk_ids"] = linked_chunk_ids
        asset["linked_count"] = len(linked_chunk_ids)

    image_lookup = {str(asset.get("image_id")): asset for asset in image_assets}
    table_lookup = {str(asset.get("table_id")): asset for asset in table_assets}

    for chunk in chunks_with_assets:
        linked_images = _find_linked_assets(chunk, image_assets, asset_key="image_id")
        linked_tables = _find_linked_assets(chunk, table_assets, asset_key="table_id")
        chunk["linked_image_ids"] = linked_images
        chunk["linked_table_ids"] = linked_tables
        metadata = dict(chunk.get("metadata") or {})
        metadata["linked_image_ids"] = linked_images
        metadata["linked_table_ids"] = linked_tables
        chunk["metadata"] = metadata

    return {
        "chunks": chunks_with_assets,
        "image_assets": image_assets,
        "table_assets": table_assets,
        "layout_blocks": [block for page in layout_pages for block in page.get("blocks", [])],
    }


def _link_asset_to_chunks(
    *,
    asset: dict[str, Any],
    chunks: list[dict[str, Any]],
    page_blocks: dict[int, list[dict[str, Any]]],
    asset_type: str,
) -> list[str]:
    page = int(asset.get("page") or asset.get("page_start") or 0)
    bbox = asset.get("bbox") or []
    candidates: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        if not _chunk_overlaps_page(chunk, page):
            continue
        score = _asset_distance_score(chunk, page_blocks.get(page, []), bbox)
        if score is None:
            continue
        candidates.append((score, chunk))

    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return []

    selected = [candidate for _, candidate in candidates[:3]]
    ids = [str(item.get("chunk_id")) for item in selected if item.get("chunk_id")]
    for chunk in selected:
        key = "linked_image_ids" if asset_type == "image" else "linked_table_ids"
        values = list(chunk.get(key) or [])
        asset_id = str(asset.get("image_id") or asset.get("table_id") or "")
        if asset_id and asset_id not in values:
            values.append(asset_id)
        chunk[key] = values
        metadata = dict(chunk.get("metadata") or {})
        metadata[key] = values
        chunk["metadata"] = metadata
    return ids


def _find_linked_assets(
    chunk: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    asset_key: str,
) -> list[str]:
    chunk_pages = _chunk_pages(chunk)
    linked: list[str] = []
    for asset in assets:
        asset_page = int(asset.get("page") or asset.get("page_start") or 0)
        if asset_page not in chunk_pages:
            continue
        asset_id = str(asset.get(asset_key) or "")
        if asset_id and asset_id not in linked:
            linked.append(asset_id)
    return linked


def _collect_chunk_bbox_list(
    chunk: dict[str, Any],
    page_blocks: dict[int, list[dict[str, Any]]],
) -> list[list[float]]:
    bbox_list: list[list[float]] = []
    for page_number in _chunk_pages(chunk):
        for block in page_blocks.get(page_number, []):
            if str(block.get("block_type")) not in {"text", "title"}:
                continue
            bbox = block.get("bbox") or []
            if isinstance(bbox, list) and len(bbox) == 4:
                bbox_list.append([float(value) for value in bbox])
    return bbox_list


def _asset_distance_score(
    chunk: dict[str, Any],
    blocks: list[dict[str, Any]],
    asset_bbox: list[Any],
) -> float | None:
    chunk_bboxes = chunk.get("bbox_list") or []
    if not chunk_bboxes and blocks:
        chunk_bboxes = [
            [float(value) for value in (block.get("bbox") or [])]
            for block in blocks
            if isinstance(block.get("bbox"), list) and len(block.get("bbox") or []) == 4
        ]
    asset_bbox = [float(value) for value in asset_bbox] if len(asset_bbox) == 4 else []
    if not asset_bbox:
        return 0.5
    if not chunk_bboxes:
        return 1.0

    distances = [_bbox_distance(asset_bbox, bbox) for bbox in chunk_bboxes if len(bbox) == 4]
    if not distances:
        return None
    return min(distances)


def _bbox_distance(a: list[float], b: list[float]) -> float:
    ax = (a[0] + a[2]) / 2
    ay = (a[1] + a[3]) / 2
    bx = (b[0] + b[2]) / 2
    by = (b[1] + b[3]) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _chunk_overlaps_page(chunk: dict[str, Any], page: int) -> bool:
    return page in _chunk_pages(chunk)


def _chunk_pages(chunk: dict[str, Any]) -> list[int]:
    page_start = int(chunk.get("page_start", 0) or 0)
    page_end = int(chunk.get("page_end", page_start) or page_start)
    if page_start <= 0 and page_end <= 0:
        return []
    if page_end < page_start:
        page_end = page_start
    return list(range(page_start, page_end + 1))


def _page_blocks_index(
    layout_pages: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for page in layout_pages:
        page_number = int(page.get("page", 0) or 0)
        index[page_number].extend(list(page.get("blocks") or []))
    return index
