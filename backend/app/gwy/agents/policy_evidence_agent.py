from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


class PolicyEvidenceState(TypedDict, total=False):
    analysis_scope: dict[str, Any]
    evidence_queries: list[str]
    policy_evidence: list[dict[str, Any]]
    reflection: dict[str, Any]
    trace: list[dict[str, Any]]
    status: str


@dataclass(slots=True)
class PolicyEvidenceAgent:
    embedding_service: EmbeddingService | None = None
    rerank_service: RerankService | None = None
    milvus_store: MilvusPolicyStore | None = None

    def __post_init__(self) -> None:
        self.embedding_service = self.embedding_service or EmbeddingService()
        self.rerank_service = self.rerank_service or RerankService()
        self.milvus_store = self.milvus_store or MilvusPolicyStore()

    def run(self, *, analysis_scope: dict[str, Any]) -> dict[str, Any]:
        state: PolicyEvidenceState = {
            "analysis_scope": dict(analysis_scope or {}),
            "trace": [],
            "status": "running",
        }
        state.update(self._plan(state))
        state.update(self._search(state))
        state.update(self._reflect(state))
        return state

    def _plan(self, state: PolicyEvidenceState) -> dict[str, Any]:
        scope = dict(state.get("analysis_scope") or {})
        queries = [
            str(query).strip()
            for query in list(scope.get("evidence_queries") or [])
            if str(query).strip()
        ]
        if not queries:
            fallback = str(scope.get("query") or scope.get("report_title") or "").strip()
            if fallback:
                queries = [fallback]

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "policy_evidence_plan",
                "agent": "PolicyEvidenceAgent",
                "skill": "policy_evidence_query_planning",
                "status": "done",
                "query_count": len(queries),
            }
        )
        return {"evidence_queries": queries, "trace": trace}

    def _search(self, state: PolicyEvidenceState) -> dict[str, Any]:
        queries = list(state.get("evidence_queries") or [])
        evidence_hits: list[dict[str, Any]] = []
        trace = list(state.get("trace") or [])

        for index, query in enumerate(queries, start=1):
            started_hits = len(evidence_hits)
            hits = self._search_policy_evidence(query)
            evidence_hits.extend(hits)
            trace.append(
                {
                    "step": "policy_evidence_search",
                    "agent": "PolicyEvidenceAgent",
                    "tool": "MilvusPolicyStore.search",
                    "backend": "Milvus + RerankService",
                    "status": "done" if hits else "empty",
                    "query_index": index,
                    "query": query,
                    "hit_count": len(hits),
                    "elapsed_hint": len(evidence_hits) - started_hits,
                }
            )

        return {"policy_evidence": evidence_hits, "trace": trace}

    def _reflect(self, state: PolicyEvidenceState) -> dict[str, Any]:
        evidence = self._deduplicate_evidence(list(state.get("policy_evidence") or []))
        missing_evidence = not evidence
        reflection = {
            "status": "partial" if missing_evidence else "completed",
            "missing_evidence": missing_evidence,
            "evidence_count": len(evidence),
            "next_action": "expand query scope" if missing_evidence else "handoff to main agent",
        }
        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "policy_evidence_reflect",
                "agent": "PolicyEvidenceAgent",
                "skill": "reflection",
                "status": reflection["status"],
                "evidence_count": len(evidence),
                "missing_evidence": missing_evidence,
            }
        )
        return {
            "policy_evidence": evidence,
            "reflection": reflection,
            "status": reflection["status"],
            "trace": trace,
        }

    def _search_policy_evidence(self, query: str) -> list[dict[str, Any]]:
        if self.embedding_service is None or self.milvus_store is None:
            return []
        try:
            vector = self.embedding_service.embed_text(query)
            hits = self.milvus_store.search(
                query_vector=vector,
                filter_expr=None,
                top_k=5,
            )
        except Exception:
            return []

        if self.rerank_service is None or not hits:
            return list(hits)
        try:
            return self.rerank_service.rerank(
                query=query,
                documents=hits,
                top_n=5,
            )
        except Exception:
            return list(hits)

    def _deduplicate_evidence(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduplicated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            key = self._evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(item)
        return deduplicated

    def _evidence_key(self, item: dict[str, Any]) -> str:
        return "::".join(
            [
                str(item.get("id") or "").strip(),
                str(item.get("doc_title") or "").strip(),
                str(item.get("source_file") or "").strip(),
                str(item.get("content") or "").strip()[:120],
            ]
        )
