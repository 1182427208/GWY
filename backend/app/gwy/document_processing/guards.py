from __future__ import annotations

import re
from typing import Any

from app.gwy.document_processing.extractors import normalize_text

NAVIGATION_NOISE_HINTS = (
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
    "京ICP备",
)


def qa_pair_guard(chunk: dict[str, Any]) -> bool:
    question = str(chunk.get("question", "")).strip()
    answer = str(chunk.get("answer", "")).strip()
    if not question or not answer:
        return False
    if _is_noise_text(question):
        return False
    if _is_noise_text(answer):
        return False
    if len(_normalize_compact(question)) < 2 or len(_normalize_compact(answer)) < 4:
        return False
    if _is_numeric_like(question) or _is_numeric_like(answer):
        return False
    return True


def table_guard(chunk: dict[str, Any]) -> bool:
    columns = list(chunk.get("columns") or [])
    rows = list(chunk.get("rows") or [])
    return len(columns) >= 2 and len(rows) >= 1


def exam_item_guard(chunk: dict[str, Any]) -> bool:
    stem = str(chunk.get("stem", "")).strip()
    image_refs = list(chunk.get("image_refs") or [])
    return bool(stem) or bool(image_refs)


def chunk_citation_guard(chunk: dict[str, Any]) -> bool:
    source_file = str(chunk.get("source_file", "")).strip()
    page_start = int(chunk.get("page_start", 0) or 0)
    page_end = int(chunk.get("page_end", 0) or 0)
    bbox = chunk.get("bbox")
    return bool(source_file) and page_start > 0 and page_end > 0 and bbox is not None


def no_split_question_answer_guard(chunk: dict[str, Any]) -> bool:
    content = str(chunk.get("content", "")).strip()
    question = str(chunk.get("question", "")).strip()
    answer = str(chunk.get("answer", "")).strip()
    if not question or not answer:
        return False
    if not content:
        return True
    return question in content and answer in content


def chunk_noise_guard(chunk: dict[str, Any]) -> bool:
    chunk_type = str(chunk.get("chunk_type") or "")
    content = str(chunk.get("content", "")).strip()
    if not content:
        return False
    if _is_noise_text(content):
        return False
    if chunk_type in {"policy_qa", "policy_section", "semantic_text"}:
        if _is_numeric_like(content):
            return False
        if _has_too_many_placeholder_tokens(content):
            return False
    if chunk_type == "table_row":
        if _has_too_many_placeholder_tokens(content):
            return False
        if _is_numeric_like(content):
            return False
        if len(_normalize_compact(content)) < 10:
            return False
    if chunk_type == "table_summary":
        if _has_too_many_placeholder_tokens(content):
            return False
        if _is_navigation_noise(content):
            return False
    return True


def is_placeholder_noise_chunk(chunk: dict[str, Any]) -> bool:
    chunk_type = str(chunk.get("chunk_type") or "")
    content = normalize_text(str(chunk.get("content", "")))
    if not content:
        return True
    if _is_noise_text(content):
        return True

    compact = _normalize_compact(content).lower()
    placeholder_hits = sum(compact.count(token) for token in ("none", "null", "nan"))
    nav_hits = sum(1 for token in NAVIGATION_NOISE_HINTS if token in content)

    if placeholder_hits >= 2:
        return True
    if placeholder_hits >= 1 and nav_hits >= 1:
        return True
    if chunk_type in {"table_row", "table_summary"} and placeholder_hits >= 1:
        return True
    if chunk_type in {"table_summary", "table_row"} and nav_hits >= 2:
        return True
    if chunk_type in {"table_summary", "table_row"} and _is_navigation_noise(content):
        return True
    if chunk_type in {"policy_qa", "policy_section", "semantic_text"}:
        if placeholder_hits >= 1 and len(compact) < 120:
            return True
    return False


def _is_noise_text(text: str) -> bool:
    normalized = _normalize_compact(text)
    if not normalized:
        return True
    if normalized in {"首页", "返回顶部", "咨询电话", "个人中心"}:
        return True
    if any(
        marker in normalized
        for marker in (
            "首页招考公告政策法规",
            "返回顶部咨询电话",
            "版权所有国家公务员局",
            "网站所有国家公务员局",
        )
    ):
        return True
    if normalized in {"1", "6", "1题", "问1答6"}:
        return True
    return False


def _is_navigation_noise(text: str) -> bool:
    normalized = _normalize_compact(text)
    if not normalized:
        return True
    hit_count = sum(1 for token in NAVIGATION_NOISE_HINTS if token in normalized)
    if hit_count >= 3:
        return True
    if "首页招考公告政策法规" in normalized and "常见问题" in normalized:
        return True
    if "版权所有" in normalized or "网站所有" in normalized or "京ICP备" in normalized:
        return True
    if "咨询电话" in normalized and ("返回顶部" in normalized or "个人中心" in normalized):
        return True
    return False


def _normalize_compact(text: str) -> str:
    return re.sub(r"[\s\u3000>><<:：,，。、《》\-_/\\|【】\[\]（）()]+", "", str(text or ""))


def _is_numeric_like(text: str) -> bool:
    compact = _normalize_compact(text)
    if not compact:
        return True
    if compact.isdigit():
        return True
    cjk_count = sum(1 for ch in compact if "\u4e00" <= ch <= "\u9fff")
    digit_count = sum(1 for ch in compact if ch.isdigit())
    if cjk_count == 0 and digit_count > 0:
        return True
    if digit_count > 0 and cjk_count < 2 and len(compact) <= 6:
        return True
    return False


def _has_too_many_placeholder_tokens(text: str) -> bool:
    normalized = _normalize_compact(text).lower()
    if not normalized:
        return True
    placeholders = ("none", "null", "nan", "暂无", "空白")
    placeholder_hits = sum(1 for token in placeholders if token in normalized)
    return placeholder_hits >= 1 and len(normalized) < 80
