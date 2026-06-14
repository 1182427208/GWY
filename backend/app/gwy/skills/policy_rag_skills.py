from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.gwy.services.hybrid_retrieval_service import HybridRetrievalService
from app.gwy.skills.policy_rag_rules import (
    build_cache_key,
    build_doc_title_hint,
    build_filter_parts,
    build_rewritten_queries,
    route_intent,
)


def route_intent_skill(query: str) -> dict[str, str | bool]:
    return route_intent(query)


def build_rewritten_queries_skill(query: str, intent: str) -> list[str]:
    return build_rewritten_queries(query, intent)


def build_metadata_filter_skill(
    *,
    year: int,
    exam_type: str,
    intent: str,
    doc_group: str,
    doc_type: str,
) -> str:
    return " and ".join(
        build_filter_parts(
            year=year,
            exam_type=exam_type,
            intent=intent,
            doc_group=doc_group,
            doc_type=doc_type,
        )
    )


def unique_queries_skill(queries: list[str]) -> list[str]:
    unique: list[str] = []
    for query in queries:
        normalized = query.strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique[:3]


def build_hybrid_results_skill(
    *,
    query: str,
    query_results: list[list[dict[str, Any]]],
    candidate_documents: list[dict[str, Any]],
    top_k: int,
    hybrid_retrieval_service: HybridRetrievalService | None = None,
) -> list[dict[str, Any]]:
    service = hybrid_retrieval_service or HybridRetrievalService()
    bm25_results = service.score_documents(
        query=query,
        documents=candidate_documents,
        top_n=max(top_k, 10),
    )
    return [*query_results, bm25_results]


def rrf_fusion_skill(
    result_lists: list[list[dict[str, Any]]],
    *,
    k: int = 60,
) -> list[dict[str, Any]]:
    fused_scores: dict[str, float] = defaultdict(float)
    items_by_id: dict[str, dict[str, Any]] = {}
    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            fused_scores[item_id] += 1.0 / (k + rank)
            items_by_id[item_id] = item
    ordered_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
    fused: list[dict[str, Any]] = []
    for item_id in ordered_ids:
        item = dict(items_by_id[item_id])
        item["rrf_score"] = fused_scores[item_id]
        fused.append(item)
    return fused


def build_session_title_skill(query: str, intent: str, excerpt_fn: Any) -> str:
    hint = build_doc_title_hint(intent)
    if hint:
        return f"{hint}：{excerpt_fn(query, 18)}"
    return excerpt_fn(query, 24)


def unique_citation_docs_skill(citations: list[dict[str, Any]]) -> list[str]:
    docs: list[str] = []
    for citation in citations:
        doc_title = str(citation.get("doc_title") or "").strip()
        if doc_title and doc_title not in docs:
            docs.append(doc_title)
    return docs

