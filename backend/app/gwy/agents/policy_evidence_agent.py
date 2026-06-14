from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


class PolicyEvidenceState(TypedDict, total=False):
    analysis_scope: dict[str, Any]
    evidence_queries: list[str]
    policy_evidence: list[dict[str, Any]]
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class PolicyEvidenceAgent:
    embedding_service: EmbeddingService | None = None
    rerank_service: RerankService | None = None
    milvus_store: MilvusPolicyStore | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.embedding_service = self.embedding_service or EmbeddingService()
        self.rerank_service = self.rerank_service or RerankService()
        self.milvus_store = self.milvus_store or MilvusPolicyStore()
        self.graph = self._build_graph()

    def run(self, *, analysis_scope: dict[str, Any]) -> dict[str, Any]:
        state: PolicyEvidenceState = {
            "analysis_scope": dict(analysis_scope or {}),
            "trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self) -> Any:
        builder = StateGraph(PolicyEvidenceState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("search", self._node_search)
        builder.add_node("observe", self._node_observe)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "search")
        builder.add_edge("search", "observe")
        builder.add_edge("observe", END)
        return builder.compile()

    def _node_plan(self, state: PolicyEvidenceState) -> dict[str, Any]:
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
                "status": "done",
                "query_count": len(queries),
            }
        )
        return {"evidence_queries": queries, "trace": trace}

    def _node_search(self, state: PolicyEvidenceState) -> dict[str, Any]:
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
                    "status": "done" if hits else "empty",
                    "query_index": index,
                    "query": query,
                    "hit_count": len(hits),
                    "elapsed_hint": len(evidence_hits) - started_hits,
                }
            )

        return {"policy_evidence": evidence_hits, "trace": trace}

    def _node_observe(self, state: PolicyEvidenceState) -> dict[str, Any]:
        evidence = self._deduplicate_evidence(list(state.get("policy_evidence") or []))
        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "policy_evidence_observe",
                "status": "done",
                "evidence_count": len(evidence),
            }
        )
        return {"policy_evidence": evidence, "trace": trace}

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
