from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


class RiskReviewState(TypedDict, total=False):
    query: str
    recommendations: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    evidence_queries: list[str]
    evidence_hits: list[dict[str, Any]]
    risk_items: list[dict[str, Any]]
    risk_level: str
    need_manual_confirm: bool
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class RiskReviewAgent:
    embedding_service: EmbeddingService | None = None
    rerank_service: RerankService | None = None
    milvus_store: MilvusPolicyStore | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        *,
        query: str,
        recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state: RiskReviewState = {
            "query": query,
            "recommendations": recommendations,
            "trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self) -> Any:
        builder = StateGraph(RiskReviewState)
        builder.add_node("analyze", self._node_analyze)
        builder.add_node("act", self._node_act)
        builder.add_node("observe", self._node_observe)
        builder.add_node("reflect", self._node_reflect)
        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "act")
        builder.add_edge("act", "observe")
        builder.add_edge("observe", "reflect")
        builder.add_edge("reflect", END)
        return builder.compile()

    def _node_analyze(self, state: RiskReviewState) -> dict[str, Any]:
        hypotheses: list[dict[str, Any]] = []
        evidence_queries: list[str] = []

        for recommendation in state.get("recommendations") or []:
            title = str(recommendation.get("job_title") or "")
            remarks = str(recommendation.get("remarks") or "")
            combined = f"{title} {remarks} {state.get('query') or ''}"
            for risk_type, trigger, suggestion in self._risk_rules():
                if trigger in combined:
                    hypothesis = {
                        "position_id": recommendation.get("position_id"),
                        "job_title": title,
                        "risk_type": risk_type,
                        "trigger": trigger,
                        "remarks": remarks,
                        "suggestion": suggestion,
                    }
                    hypotheses.append(hypothesis)
                    evidence_queries.append(self._build_evidence_query(title, trigger))

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "risk_intent_analysis",
                "hypothesis_count": len(hypotheses),
            }
        )
        return {
            "hypotheses": hypotheses,
            "evidence_queries": self._deduplicate(evidence_queries),
            "trace": trace,
        }

    def _node_act(self, state: RiskReviewState) -> dict[str, Any]:
        evidence_hits: list[dict[str, Any]] = []
        evidence_queries = list(state.get("evidence_queries") or [])
        for query in evidence_queries:
            evidence_hits.extend(self._search_policy_evidence(query))

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "risk_act",
                "evidence_query_count": len(evidence_queries),
                "evidence_hit_count": len(evidence_hits),
            }
        )
        return {
            "evidence_hits": evidence_hits,
            "trace": trace,
        }

    def _node_observe(self, state: RiskReviewState) -> dict[str, Any]:
        evidence_hits = list(state.get("evidence_hits") or [])
        risk_items: list[dict[str, Any]] = []

        for hypothesis in state.get("hypotheses") or []:
            matched_evidence = self._match_evidence(hypothesis, evidence_hits)
            risk_level = "high" if matched_evidence and len(matched_evidence) > 1 else "medium"
            if not matched_evidence and hypothesis.get("trigger") in {"专业测试", "基层", "户籍", "证书", "加班", "值班"}:
                risk_level = "medium"
            risk_items.append(
                {
                    "risk_type": hypothesis.get("risk_type"),
                    "risk_level": risk_level,
                    "evidence": matched_evidence[0].get("content") if matched_evidence else hypothesis.get("remarks") or hypothesis.get("trigger"),
                    "explanation": self._explain_risk(hypothesis, matched_evidence),
                    "suggestion": hypothesis.get("suggestion"),
                    "need_manual_confirm": bool(matched_evidence) or risk_level == "high",
                    "source": matched_evidence[0].get("doc_title") if matched_evidence else None,
                }
            )

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "risk_observe",
                "risk_item_count": len(risk_items),
            }
        )
        return {
            "risk_items": risk_items,
            "trace": trace,
        }

    def _node_reflect(self, state: RiskReviewState) -> dict[str, Any]:
        risk_items = list(state.get("risk_items") or [])
        high_risk_count = sum(1 for item in risk_items if item.get("risk_level") == "high")
        medium_risk_count = sum(1 for item in risk_items if item.get("risk_level") == "medium")
        need_manual_confirm = any(bool(item.get("need_manual_confirm")) for item in risk_items)
        if high_risk_count >= 2:
            risk_level = "high"
        elif high_risk_count == 1 or medium_risk_count >= 2 or need_manual_confirm:
            risk_level = "medium"
        elif risk_items:
            risk_level = "medium"
        else:
            risk_level = "low"

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "step": "risk_reflect",
                "risk_level": risk_level,
                "need_manual_confirm": need_manual_confirm,
            }
        )
        return {
            "risk_level": risk_level,
            "need_manual_confirm": need_manual_confirm,
            "risk_items": risk_items,
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
                top_k=3,
            )
        except Exception:
            return []

        if self.rerank_service is None or not hits:
            return list(hits)
        try:
            return self.rerank_service.rerank(
                query=query,
                documents=hits,
                top_n=3,
            )
        except Exception:
            return list(hits)

    def _match_evidence(
        self,
        hypothesis: dict[str, Any],
        evidence_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        trigger = str(hypothesis.get("trigger") or "")
        matched: list[dict[str, Any]] = []
        for hit in evidence_hits:
            content = str(hit.get("content") or "")
            if trigger and trigger in content:
                matched.append(hit)
        return matched

    def _explain_risk(
        self,
        hypothesis: dict[str, Any],
        evidence_hits: list[dict[str, Any]],
    ) -> str:
        trigger = str(hypothesis.get("trigger") or "风险信号")
        if evidence_hits:
            titles = [str(hit.get("doc_title") or hit.get("source_file") or "") for hit in evidence_hits[:2]]
            titles = [title for title in titles if title]
            if titles:
                return f"证据中命中了“{trigger}”，并且已找到相关来源：{'；'.join(titles)}。"
            return f"证据中命中了“{trigger}”，建议继续核对原文。"
        return f"岗位信息里出现了“{trigger}”相关表述，需要人工复核。"

    def _risk_rules(self) -> list[tuple[str, str, str]]:
        return [
            ("service_year_limit", "基层", "确认基层经历年限是否满足岗位要求"),
            ("professional_test", "专业测试", "确认面试或专业测试要求"),
            ("household_limit", "户籍", "确认户籍限制与落户要求"),
            ("certificate_limit", "证书", "确认资格证书是否必须提交"),
            ("shift_limit", "值班", "确认是否存在值班和加班要求"),
            ("travel_limit", "出差", "确认出差频率和强度"),
            ("fresh_graduate_limit", "应届", "确认应届身份是否会影响报考"),
        ]

    def _build_evidence_query(self, title: str, trigger: str) -> str:
        parts = [part for part in [title, trigger, "官方公告", "资格条件"] if part]
        return " ".join(parts)

    def _deduplicate(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduplicated: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(normalized)
        return deduplicated
