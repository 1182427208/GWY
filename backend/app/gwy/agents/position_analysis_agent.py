from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlmodel import Session, select

from app.gwy.agents.policy_evidence_agent import PolicyEvidenceAgent
from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
from app.gwy.agents.risk_review_agent import RiskReviewAgent
from app.gwy.agents.web_verification_agent import WebVerificationAgent
from app.gwy.llm.chat_service import ChatService
from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.models import GwyPositionAnalysisSnapshot, GwyUserProfile
from app.gwy.prompts.position_analysis import (
    POSITION_ANALYSIS_SYSTEM_PROMPT,
    POSITION_ANALYSIS_USER_PROMPT_TEMPLATE,
    POSITION_RESEARCH_SYSTEM_PROMPT,
    POSITION_RESEARCH_USER_PROMPT_TEMPLATE,
)
from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
from app.gwy.services.position_catalog_service import PositionCatalogService
from app.gwy.services.web_fetch_service import WebFetchService
from app.gwy.services.web_search_service import WebSearchService
from app.gwy.skills.position_analysis_skills import (
    build_analysis_clarification,
    build_analysis_scope,
    build_analysis_strategy,
    build_position_research_plan,
    cleanup_analysis_report,
    normalize_analysis_snapshot,
    render_analysis_outline,
    summarize_position_history,
)
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


POSITION_STRATEGY_PLANNER_SYSTEM_PROMPT = """
你是 GwyPilot 的岗位分析规划器。

你的任务不是直接写最终报告，而是先根据用户画像、岗位池、历史趋势和政策证据，输出一份可执行的分析计划。

要求：
- 采用 Plan-and-Solve 思路先规划，再用 ReAct 思路做外网补证与重试。
- 你必须优先关注 2024-2026 年招录人数、报录比、进面分和备注限制。
- 不能编造不存在的数据；无法确认就写成 missing 或 unknown。
- 输出必须是严格 JSON，不要输出 Markdown，不要加解释，不要加代码块。
- 需要包含每个重点岗位的搜索目标、补证目标和重试条件。
""".strip()


class PositionAnalysisState(TypedDict, total=False):
    snapshot_id: str | None
    task_id: str | None
    user_id: str | None
    user_profile: dict[str, Any] | None
    recommendation_context: dict[str, Any] | None
    snapshot: dict[str, Any]
    normalized_snapshot: dict[str, Any]
    analysis_scope: dict[str, Any]
    position_facts: dict[str, Any]
    policy_evidence: list[dict[str, Any]]
    analysis_strategy: dict[str, Any]
    research_observations: list[dict[str, Any]]
    analysis_decision: dict[str, Any]
    position_researches: list[dict[str, Any]]
    research_plan: dict[str, Any]
    retry_round: int
    retry_budget: int
    retry_targets: list[dict[str, Any]]
    needs_retry: bool
    risk_review: dict[str, Any]
    report_outline: list[str]
    report_draft: str
    report: str
    report_meta: dict[str, Any]
    status: str
    stage: str
    needs_more_info: bool
    missing_fields: list[str]
    clarifying_questions: list[str]
    clarification_reason: str
    output_json: dict[str, Any]
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class PositionAnalysisAgent:
    session: Session | None = None
    position_catalog_service: PositionCatalogService | None = None
    embedding_service: EmbeddingService | None = None
    rerank_service: RerankService | None = None
    milvus_store: MilvusPolicyStore | None = None
    web_search_service: WebSearchService | None = None
    web_fetch_service: WebFetchService | None = None
    browser_service: PlaywrightMCPService | None = None
    policy_evidence_agent: PolicyEvidenceAgent | None = None
    web_verification_agent: WebVerificationAgent | None = None
    risk_review_agent: RiskReviewAgent | None = None
    report_generator_agent: ReportGeneratorAgent | None = None
    chat_service: ChatService | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.position_catalog_service is None and self.session is not None:
            self.position_catalog_service = PositionCatalogService(self.session)
        self.embedding_service = self.embedding_service or EmbeddingService()
        self.rerank_service = self.rerank_service or RerankService()
        self.milvus_store = self.milvus_store or MilvusPolicyStore()
        self.web_search_service = self.web_search_service or WebSearchService()
        self.browser_service = self.browser_service or PlaywrightMCPService()
        self.web_fetch_service = self.web_fetch_service or WebFetchService()
        self.policy_evidence_agent = self.policy_evidence_agent or PolicyEvidenceAgent(
            embedding_service=self.embedding_service,
            rerank_service=self.rerank_service,
            milvus_store=self.milvus_store,
        )
        self.web_verification_agent = self.web_verification_agent or WebVerificationAgent(
            web_search_service=self.web_search_service,
            web_fetch_service=self.web_fetch_service,
            browser_service=self.browser_service,
        )
        self.risk_review_agent = self.risk_review_agent or RiskReviewAgent(
            embedding_service=self.embedding_service,
            rerank_service=self.rerank_service,
            milvus_store=self.milvus_store,
        )
        self.report_generator_agent = self.report_generator_agent or ReportGeneratorAgent(
            chat_service=self.chat_service,
        )
        self.graph = self._build_graph()

    def run(
        self,
        *,
        snapshot: dict[str, Any] | None = None,
        snapshot_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        user_profile: dict[str, Any] | None = None,
        recommendation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state: PositionAnalysisState = {
            "snapshot": dict(snapshot or {}),
            "snapshot_id": str(snapshot_id) if snapshot_id else None,
            "task_id": str(task_id) if task_id else None,
            "user_id": str(user_id) if user_id else None,
            "user_profile": dict(user_profile or {}),
            "recommendation_context": dict(recommendation_context or {}),
            "retry_round": 0,
            "retry_budget": 1,
            "retry_targets": [],
            "needs_retry": False,
            "trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self) -> Any:
        builder = StateGraph(PositionAnalysisState)
        builder.add_node("load_snapshot", self._node_load_snapshot)
        builder.add_node("normalize_snapshot", self._node_normalize_snapshot)
        builder.add_node(
            "ingest_recommendation_context",
            self._node_ingest_recommendation_context,
        )
        builder.add_node("build_analysis_scope", self._node_build_analysis_scope)
        builder.add_node("clarify_requirements", self._node_clarify_requirements)
        builder.add_node("retrieve_position_facts", self._node_retrieve_position_facts)
        builder.add_node("plan_analysis_strategy", self._node_plan_analysis_strategy)
        builder.add_node("research_positions", self._node_research_positions)
        builder.add_node("observe_research_gaps", self._node_observe_research_gaps)
        builder.add_node("retry_research", self._node_retry_research)
        builder.add_node("decide_report_focus", self._node_decide_report_focus)
        builder.add_node("retrieve_policy_evidence", self._node_retrieve_policy_evidence)
        builder.add_node("risk_review", self._node_risk_review)
        builder.add_node("compose_report", self._node_compose_report)
        builder.add_node("refine_report", self._node_refine_report)
        builder.add_node("persist_result", self._node_persist_result)
        builder.add_edge(START, "load_snapshot")
        builder.add_edge("load_snapshot", "normalize_snapshot")
        builder.add_edge("normalize_snapshot", "build_analysis_scope")
        builder.add_edge("build_analysis_scope", "ingest_recommendation_context")
        builder.add_conditional_edges(
            "ingest_recommendation_context",
            self._route_after_scope,
            {
                "clarify_requirements": "clarify_requirements",
                "continue_analysis": "retrieve_position_facts",
            },
        )
        builder.add_edge("clarify_requirements", "persist_result")
        builder.add_edge("retrieve_position_facts", "retrieve_policy_evidence")
        builder.add_edge("retrieve_policy_evidence", "plan_analysis_strategy")
        builder.add_edge("plan_analysis_strategy", "research_positions")
        builder.add_edge("research_positions", "observe_research_gaps")
        builder.add_conditional_edges(
            "observe_research_gaps",
            self._route_after_observe,
            {
                "retry_research": "retry_research",
                "decide_report_focus": "decide_report_focus",
            },
        )
        builder.add_edge("retry_research", "decide_report_focus")
        builder.add_edge("decide_report_focus", "risk_review")
        builder.add_edge("risk_review", "compose_report")
        builder.add_edge("compose_report", "refine_report")
        builder.add_edge("refine_report", "persist_result")
        builder.add_edge("persist_result", END)
        return builder.compile()

    def _node_load_snapshot(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        snapshot = dict(state.get("snapshot") or {})
        loaded_from = "input"

        if not snapshot and self.session is not None and state.get("snapshot_id"):
            snapshot_uuid = UUID(str(state["snapshot_id"]))
            row = self.session.get(GwyPositionAnalysisSnapshot, snapshot_uuid)
            if row is None:
                raise ValueError(f"Position analysis snapshot not found: {snapshot_uuid}")
            snapshot = self._serialize_snapshot_row(row)
            loaded_from = "database"

        if not snapshot:
            raise ValueError("Position analysis snapshot is required.")

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="load_snapshot",
                status="done",
                detail="宸已加载岗位分析快照",
                started_at=started_at,
                inputs_summary={
                    "snapshot_id": state.get("snapshot_id"),
                    "user_id": state.get("user_id"),
                },
                outputs_summary={
                    "loaded_from": loaded_from,
                    "title": snapshot.get("title"),
                },
            )
        )
        return {"snapshot": snapshot, "trace": trace}

    def _node_normalize_snapshot(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        normalized = normalize_analysis_snapshot(state.get("snapshot") or {})
        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="normalize_snapshot",
                status="done",
                detail="宸叉爣鍑嗗寲蹇収瀛楁",
                started_at=started_at,
                inputs_summary={
                    "title": normalized.get("title"),
                    "selected_position_ids": list(normalized.get("selected_position_ids") or []),
                },
                outputs_summary={
                    "visible_columns": list(normalized.get("visible_columns") or []),
                    "notes": normalized.get("notes") or "",
                },
            )
        )
        return {"normalized_snapshot": normalized, "trace": trace}

    def _node_ingest_recommendation_context(
        self,
        state: PositionAnalysisState,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        recommendation_context = dict(state.get("recommendation_context") or {})
        trace = list(state.get("trace") or [])
        status = "done" if recommendation_context else "skipped"
        detail = (
            "已接收前置推荐 Agent 产出的规划上下文"
            if recommendation_context
            else "当前没有前置推荐上下文，直接进入岗位分析"
        )
        trace.append(
            self._trace_entry(
                step="ingest_recommendation_context",
                status=status,
                detail=detail,
                started_at=started_at,
                inputs_summary={
                    "has_context": bool(recommendation_context),
                    "recommendation_count": len(
                        list(recommendation_context.get("recommendations") or [])
                    ),
                    "need_more_info": bool(
                        recommendation_context.get("need_more_info")
                    ),
                },
                outputs_summary={
                    "query": recommendation_context.get("query"),
                    "year": recommendation_context.get("year"),
                    "exam_type": recommendation_context.get("exam_type"),
                },
            )
        )
        return {
            "recommendation_context": recommendation_context,
            "trace": trace,
        }

    def _node_build_analysis_scope(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        profile = self._load_user_profile(state)
        scope = build_analysis_scope(
            state.get("normalized_snapshot") or {},
            profile=profile,
        )
        recommendation_context = dict(state.get("recommendation_context") or {})
        if recommendation_context:
            scope["recommendation_context"] = recommendation_context
        clarification = build_analysis_clarification(scope, profile=profile)
        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="build_analysis_scope",
                status="done",
                detail="宸已生成分析范围",
                started_at=started_at,
                inputs_summary={
                    "selected_count": scope.get("selected_count", 0),
                    "query": scope.get("query"),
                    "profile_loaded": bool(profile),
                },
                outputs_summary={
                    "report_title": scope.get("report_title"),
                    "evidence_query_count": len(scope.get("evidence_queries") or []),
                    "recommendation_count": len(
                        list(recommendation_context.get("recommendations") or [])
                    ),
                    "needs_more_info": bool(clarification.get("needs_more_info")),
                    "missing_field_count": len(clarification.get("missing_fields") or []),
                    "question_count": len(clarification.get("clarifying_questions") or []),
                },
            )
        )
        return {
            "analysis_scope": scope,
            "user_profile": profile,
            "recommendation_context": recommendation_context,
            "needs_more_info": bool(clarification.get("needs_more_info")),
            "missing_fields": list(clarification.get("missing_fields") or []),
            "clarifying_questions": list(clarification.get("clarifying_questions") or []),
            "clarification_reason": str(clarification.get("clarification_reason") or ""),
            "trace": trace,
        }

    def _route_after_scope(self, state: PositionAnalysisState) -> str:
        return "clarify_requirements" if state.get("needs_more_info") else "continue_analysis"

    def _node_clarify_requirements(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        questions = list(state.get("clarifying_questions") or [])
        missing_fields = list(state.get("missing_fields") or [])
        reason = str(state.get("clarification_reason") or "")
        report = self._build_clarification_report(
            title=str((state.get("analysis_scope") or {}).get("report_title") or "宀椾綅鍒嗘瀽鎶ュ憡"),
            reason=reason,
            questions=questions,
            missing_fields=missing_fields,
        )
        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="clarify_requirements",
                status="done",
                detail="当前信息不足，先向用户追问补充信息",
                started_at=started_at,
                inputs_summary={
                    "missing_fields": list(missing_fields),
                },
                outputs_summary={
                    "question_count": len(questions),
                    "needs_more_info": True,
                },
            )
        )
        output_json = {
            "needs_more_info": True,
            "missing_fields": missing_fields,
            "clarifying_questions": questions,
            "clarification_reason": reason,
            "report_outline": ["直接结论", "需要补充的信息", "下一步建议"],
        }
        return {
            "status": "needs_more_info",
            "stage": "clarify_requirements",
            "report": report,
            "report_draft": report,
            "report_outline": list(output_json["report_outline"]),
            "needs_more_info": True,
            "missing_fields": missing_fields,
            "clarifying_questions": questions,
            "clarification_reason": reason,
            "trace": trace,
            "output_json": output_json,
        }

    def _build_clarification_report(
        self,
        *,
        title: str,
        reason: str,
        questions: list[str],
        missing_fields: list[str],
    ) -> str:
        lines = [
            f"# {title}",
            "",
            "## 直接结论",
            "当前信息不足，先补充关键信息后再生成完整分析报告。",
            "",
            "## 需要补充的信息",
        ]
        if missing_fields:
            for item in missing_fields:
                human_readable = self._map_missing_fields_to_chinese([item])
                label = human_readable[0] if human_readable else item
                lines.append(f"- {label}")
        if questions:
            lines.append("")
            lines.append("### 追问")
            for index, question in enumerate(questions, start=1):
                lines.append(f"{index}. {question}")
        lines.extend(
            [
                "",
                "## 下一步建议",
                "- 你把上面的问题补充给我后，我会继续按岗位事实、政策证据和风险点生成正式报告。",
                "- 如果你愿意，也可以直接补充专业、学历、学位、地区和政治面貌，我可以一次性继续往下分析。",
            ]
        )
        if reason:
            lines.extend(["", "## Agent 鍒ゆ柇", f"- {reason}"])
        return cleanup_analysis_report("\n".join(lines))

    def _map_missing_fields_to_chinese(self, fields: list[str]) -> list[str]:
        mapping = {
            "major": "涓撲笟",
            "education": "瀛﹀巻",
            "degree": "瀛︿綅",
            "political_status": "鏀挎不闈㈣矊",
            "target_regions": "鍦板尯鍋忓ソ",
            "desired_departments": "閮ㄩ棬鍋忓ソ",
            "desired_positions": "宀椾綅鍋忓ソ",
            "grassroots_experience_years": "鍩哄眰缁忓巻",
        }
        return [mapping.get(field, field) for field in fields]

    def _node_retrieve_position_facts(
        self,
        state: PositionAnalysisState,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        selected_position_ids = _parse_uuid_list(
            list(scope.get("selected_position_ids") or [])
        )
        catalog_result: dict[str, Any]

        if self.position_catalog_service is None:
            catalog_result = {
                "analysis": "position catalog unavailable",
                "summary": {
                    "candidate_count": len(selected_position_ids),
                    "filtered_count": len(selected_position_ids),
                    "recommendation_count": 0,
                    "top_positions": [],
                },
                "recommendations": [],
                "selected_positions": [],
                "retrieval_trace": [],
            }
        else:
            catalog_result = self.position_catalog_service.analyze_positions(
                position_ids=selected_position_ids,
                query=str(scope.get("query") or scope.get("report_title") or ""),
                profile=dict(scope.get("effective_profile") or {}),
                top_k=max(1, len(selected_position_ids) or 5),
            )

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="retrieve_position_facts",
                status="done",
                detail="已检索 PostgreSQL 岗位事实",
                started_at=started_at,
                inputs_summary={
                    "selected_position_count": len(selected_position_ids),
                    "query": scope.get("query"),
                },
                outputs_summary={
                    "recommendation_count": len(catalog_result.get("recommendations") or []),
                    "selected_position_count": len(catalog_result.get("selected_positions") or []),
                },
            )
        )
        trace.extend(list(catalog_result.get("retrieval_trace") or []))
        return {"position_facts": catalog_result, "trace": trace}

    def _node_retrieve_policy_evidence(
        self,
        state: PositionAnalysisState,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        evidence_queries = list(scope.get("evidence_queries") or [scope.get("query") or ""])
        policy_result = self.policy_evidence_agent.run(analysis_scope=scope)
        deduplicated = list(policy_result.get("policy_evidence") or [])
        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="retrieve_policy_evidence",
                status="done",
                detail="已检索 Milvus 政策证据",
                started_at=started_at,
                inputs_summary={
                    "evidence_query_count": len(evidence_queries),
                },
                outputs_summary={
                    "evidence_hit_count": len(deduplicated),
                },
                evidence_refs=[
                    _build_evidence_ref(item) for item in deduplicated[:5]
                ],
            )
        )
        trace.extend(list(policy_result.get("trace") or []))
        return {"policy_evidence": deduplicated, "trace": trace}

    def _node_plan_analysis_strategy(
        self,
        state: PositionAnalysisState,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        position_facts = dict(state.get("position_facts") or {})
        policy_evidence = list(state.get("policy_evidence") or [])
        base_strategy = build_analysis_strategy(
            scope,
            position_facts=position_facts,
            policy_evidence=policy_evidence,
        )
        llm_strategy = self._build_llm_analysis_strategy(
            scope=scope,
            position_facts=position_facts,
            policy_evidence=policy_evidence,
            base_strategy=base_strategy,
        )
        strategy = self._merge_analysis_strategies(base_strategy, llm_strategy)

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="plan_analysis_strategy",
                status="done",
                detail="已生成策略驱动的研究计划",
                started_at=started_at,
                inputs_summary={
                    "selected_position_count": len(
                        list(position_facts.get("selected_positions") or [])
                    ),
                    "policy_evidence_count": len(policy_evidence),
                },
                outputs_summary={
                    "strategy_name": strategy.get("strategy_name"),
                    "planning_strategy": strategy.get("planning_strategy"),
                    "evidence_strategy": strategy.get("evidence_strategy"),
                    "research_target_count": len(strategy.get("research_targets") or []),
                    "strategy_source": strategy.get("strategy_source") or "deterministic",
                },
            )
        )
        return {
            "analysis_strategy": strategy,
            "research_plan": dict(strategy.get("research_plan") or {}),
            "trace": trace,
        }

    def _build_llm_analysis_strategy(
        self,
        *,
        scope: dict[str, Any],
        position_facts: dict[str, Any],
        policy_evidence: list[dict[str, Any]],
        base_strategy: dict[str, Any],
    ) -> dict[str, Any]:
        if self.chat_service is None:
            return {}

        selected_positions = list(position_facts.get("selected_positions") or [])
        recommendations = list(position_facts.get("recommendations") or [])
        payload = {
            "analysis_scope": {
                "report_title": scope.get("report_title"),
                "analysis_goal": scope.get("analysis_goal"),
                "query": scope.get("query"),
                "year": scope.get("year"),
                "selected_count": scope.get("selected_count"),
                "missing_fields": scope.get("missing_fields") or [],
            },
            "user_profile": scope.get("profile_summary") or scope.get("effective_profile") or {},
            "position_summary": position_facts.get("summary") or {},
            "selected_positions": [
                self._summarize_strategy_position(item, index=index)
                for index, item in enumerate(selected_positions[:6], start=1)
            ],
            "recommendations": [
                self._summarize_strategy_position(item, index=index)
                for index, item in enumerate(recommendations[:6], start=1)
            ],
            "policy_evidence": [
                {
                    "doc_title": str(item.get("doc_title") or item.get("source_file") or ""),
                    "doc_group": item.get("doc_group"),
                    "doc_type": item.get("doc_type"),
                    "year": item.get("year"),
                    "snippet": str(item.get("content") or "")[:260],
                }
                for item in policy_evidence[:5]
            ],
            "base_strategy": {
                "strategy_name": base_strategy.get("strategy_name"),
                "planning_strategy": base_strategy.get("planning_strategy"),
                "evidence_strategy": base_strategy.get("evidence_strategy"),
                "decision_style": base_strategy.get("decision_style"),
                "priority_sources": base_strategy.get("priority_sources"),
                "research_targets": base_strategy.get("research_targets"),
                "summary_lines": base_strategy.get("summary_lines"),
            },
        }
        prompt = (
            "请基于下方结构化信息，为岗位分析生成一份可执行研究策略 JSON。\n"
            "输出字段至少包括：strategy_name, planning_strategy, evidence_strategy, decision_style,\n"
            "summary_lines, priority_sources, research_targets, research_plan, decision_notes。\n"
            "其中 research_targets 每项都要包含 position_id, index, history_priority, needs_web_search,\n"
            "focus, search_queries, retry_queries, observation_questions, evidence_focus。\n"
            "请优先让 search_queries 贴近官方公告、招考简章、历年招录、报录比、进面分等真实可核验内容。\n\n"
            f"{_format_json_block(payload)}"
        )
        messages = [
            {"role": "system", "content": POSITION_STRATEGY_PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = self.chat_service.chat_completion(messages, temperature=0.2)
            parsed = self._parse_json_object(str(raw or ""))
            if isinstance(parsed, dict):
                normalized = self._normalize_llm_strategy(parsed, base_strategy=base_strategy)
                if normalized:
                    normalized["strategy_source"] = "llm"
                    return normalized
        except Exception:
            pass
        return {}

    def _merge_analysis_strategies(
        self,
        base_strategy: dict[str, Any],
        llm_strategy: dict[str, Any],
    ) -> dict[str, Any]:
        if not llm_strategy:
            merged = dict(base_strategy)
            merged["strategy_source"] = "deterministic"
            return merged

        merged = dict(base_strategy)
        for key in (
            "strategy_name",
            "planning_strategy",
            "evidence_strategy",
            "decision_style",
            "analysis_goal",
            "query",
            "research_budget",
            "priority_sources",
            "summary_lines",
            "decision_notes",
            "research_plan",
        ):
            value = llm_strategy.get(key)
            if value not in (None, "", [], {}):
                merged[key] = value

        merged_targets = self._merge_strategy_targets(
            list(base_strategy.get("research_targets") or []),
            list(llm_strategy.get("research_targets") or []),
        )
        if merged_targets:
            merged["research_targets"] = merged_targets
        merged["strategy_source"] = llm_strategy.get("strategy_source") or "llm"
        return merged

    def _merge_strategy_targets(
        self,
        base_targets: list[dict[str, Any]],
        llm_targets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not llm_targets:
            return list(base_targets)

        merged: list[dict[str, Any]] = []
        llm_index: dict[str, dict[str, Any]] = {
            str(item.get("position_id") or ""): dict(item)
            for item in llm_targets
            if str(item.get("position_id") or "").strip()
        }
        for base_item in base_targets:
            position_id = str(base_item.get("position_id") or "").strip()
            candidate = dict(base_item)
            if position_id and position_id in llm_index:
                candidate.update(
                    {
                        key: value
                        for key, value in llm_index[position_id].items()
                        if value not in (None, "", [], {})
                    }
                )
            merged.append(candidate)

        for position_id, item in llm_index.items():
            if not any(str(base.get("position_id") or "") == position_id for base in merged):
                merged.append(item)
        return merged

    def _normalize_llm_strategy(
        self,
        value: dict[str, Any],
        *,
        base_strategy: dict[str, Any],
    ) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key in (
            "strategy_name",
            "planning_strategy",
            "evidence_strategy",
            "decision_style",
            "analysis_goal",
            "query",
            "decision_notes",
        ):
            text_value = value.get(key)
            if isinstance(text_value, str):
                text_value = text_value.strip()
            if text_value not in (None, "", [], {}):
                normalized[key] = text_value

        if isinstance(value.get("research_budget"), dict):
            normalized["research_budget"] = {
                **dict(base_strategy.get("research_budget") or {}),
                **dict(value.get("research_budget") or {}),
            }
        if isinstance(value.get("priority_sources"), list):
            normalized["priority_sources"] = [
                str(item).strip() for item in value.get("priority_sources") or [] if str(item).strip()
            ]
        if isinstance(value.get("summary_lines"), list):
            normalized["summary_lines"] = [
                str(item).strip() for item in value.get("summary_lines") or [] if str(item).strip()
            ]
        if isinstance(value.get("research_targets"), list):
            normalized["research_targets"] = [
                self._normalize_llm_strategy_target(item)
                for item in value.get("research_targets") or []
                if self._normalize_llm_strategy_target(item) is not None
            ]
        if isinstance(value.get("research_plan"), dict):
            normalized["research_plan"] = dict(value.get("research_plan") or {})
        return normalized

    def _normalize_llm_strategy_target(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        position_id = str(item.get("position_id") or "").strip()
        if not position_id:
            return None
        normalized: dict[str, Any] = {"position_id": position_id}
        for key in (
            "index",
            "department_name",
            "office_name",
            "job_title",
            "position_code",
            "history_priority",
            "needs_web_search",
            "focus",
            "search_queries",
            "retry_queries",
            "observation_questions",
            "evidence_focus",
        ):
            value = item.get(key)
            if value not in (None, "", [], {}):
                if key in {"focus", "search_queries", "retry_queries", "observation_questions", "evidence_focus"}:
                    normalized[key] = [
                        str(entry).strip()
                        for entry in list(value)[:10]
                        if str(entry).strip()
                    ]
                else:
                    normalized[key] = value
        return normalized

    def _summarize_strategy_position(
        self,
        item: dict[str, Any],
        *,
        index: int,
    ) -> dict[str, Any]:
        history = dict(item.get("history") or {})
        history_summary = dict(history.get("summary") or {})
        return {
            "index": index,
            "position_id": item.get("position_id") or item.get("id"),
            "department_name": item.get("department_name"),
            "office_name": item.get("office_name"),
            "job_title": item.get("job_title"),
            "position_code": item.get("position_code"),
            "history_years": list(history_summary.get("history_years") or []),
            "latest_recruit_count": history_summary.get("latest_recruit_count"),
            "latest_interview_ratio": history_summary.get("latest_interview_ratio"),
            "recruit_count_trend": history_summary.get("recruit_count_trend"),
            "interview_ratio_trend": history_summary.get("interview_ratio_trend"),
            "web_hit_count": len(list(item.get("web_results") or [])),
            "remarks": str(item.get("remarks") or "")[:180],
        }

    def _node_research_positions(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        position_facts = dict(state.get("position_facts") or {})
        selected_positions = list(position_facts.get("selected_positions") or [])
        recommendations = list(position_facts.get("recommendations") or [])
        analysis_strategy = dict(state.get("analysis_strategy") or {})
        research_plan = dict(analysis_strategy.get("research_plan") or {})
        if not research_plan:
            research_plan = build_position_research_plan(
                scope=scope,
                position_facts=position_facts,
                max_positions=min(
                    max(len(selected_positions), len(recommendations), 1), 6
                ),
            )

        strategy_research_targets = list(analysis_strategy.get("research_targets") or [])
        research_targets = list(strategy_research_targets)
        if not research_targets:
            research_targets = selected_positions or recommendations
            research_targets = list(research_targets[:6])
        research_items: list[dict[str, Any]] = []
        trace = list(state.get("trace") or [])

        for index, position in enumerate(research_targets, start=1):
            history = (
                self.position_catalog_service.get_position_history(position, limit=5)
                if self.position_catalog_service is not None
                else {
                    "match_basis": "none",
                    "records": [],
                    "summary": {
                        "record_count": 0,
                        "history_years": [],
                        "recruit_count_trend": "unknown",
                        "interview_ratio_trend": "unknown",
                        "latest_recruit_count": None,
                        "latest_interview_ratio": None,
                    },
                }
            )
            history_summary = summarize_position_history(history)
            web_results: list[dict[str, Any]] = []
            web_search_attempts: list[dict[str, Any]] = []
            strategy_target = (
                strategy_research_targets[index - 1]
                if index - 1 < len(strategy_research_targets)
                else {}
            )
            target_plan = dict(research_plan)
            if strategy_target:
                target_plan["target_directives"] = dict(strategy_target)
            research_targets_for_web = self._build_web_research_targets(
                position=position,
                history_summary=history_summary,
                history_records=list(history.get("records") or []),
                scope=scope,
                strategy_target=strategy_target,
            )
            if strategy_target.get("needs_web_search", True):
                web_search_result = self.web_verification_agent.run(
                    position=position,
                    history_summary=history_summary,
                    history_records=list(history.get("records") or []),
                    scope=scope,
                    planned_queries=list(strategy_target.get("search_queries") or []),
                    research_targets=research_targets_for_web,
                )
                web_results = list(web_search_result.get("web_results") or [])
                web_search_attempts = list(
                    web_search_result.get("web_search_attempts") or []
                )
                trace.extend(list(web_search_result.get("trace") or []))
            analysis_text = self._generate_position_research_text(
                position=position,
                history_summary=history_summary,
                history_records=list(history.get("records") or []),
                web_results=web_results,
                web_search_attempts=web_search_attempts,
                scope=scope,
                research_plan=target_plan,
                policy_evidence=list(state.get("policy_evidence") or []),
            )
            research_items.append(
                {
                    "index": index,
                    "position_id": position.get("position_id") or position.get("id"),
                    "department_name": position.get("department_name"),
                    "office_name": position.get("office_name"),
                    "job_title": position.get("job_title"),
                    "position_code": position.get("position_code"),
                    "history": history_summary,
                    "history_records": list(history.get("records") or []),
                    "web_results": web_results,
                    "web_search_attempts": web_search_attempts,
                    "analysis_text": analysis_text,
                    "research_plan": target_plan,
                    "strategy_target": strategy_target,
                }
            )

        trace.append(
            self._trace_entry(
                step="research_positions",
                status="done",
                detail="宸已按策略完成逐岗深度研究",
                started_at=started_at,
                inputs_summary={
                    "selected_position_count": len(research_targets),
                    "recommendation_count": len(recommendations),
                },
                outputs_summary={
                    "research_item_count": len(research_items),
                    "web_hit_count": sum(len(item.get("web_results") or []) for item in research_items),
                    "retry_count": sum(
                        sum(1 for attempt in list(item.get("web_search_attempts") or []) if attempt.get("is_retry"))
                        for item in research_items
                    ),
                },
            )
        )
        return {
            "position_researches": research_items,
            "research_plan": research_plan,
            "analysis_strategy": analysis_strategy,
            "trace": trace,
        }

    def _route_after_observe(self, state: PositionAnalysisState) -> str:
        if bool(state.get("needs_retry")):
            return "retry_research"
        return "decide_report_focus"

    def _node_observe_research_gaps(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        position_researches = list(state.get("position_researches") or [])
        observations: list[dict[str, Any]] = []
        retry_targets: list[dict[str, Any]] = []
        retry_budget = int(state.get("retry_budget") or 0)
        retry_round = int(state.get("retry_round") or 0)

        for item in position_researches:
            history = dict(item.get("history") or {})
            history_records = list(item.get("history_records") or [])
            web_results = list(item.get("web_results") or [])
            web_search_attempts = list(item.get("web_search_attempts") or [])
            gaps: list[str] = []

            if not history_records:
                gaps.append("history_sparse")
            if history.get("latest_recruit_count") is None:
                gaps.append("missing_recruit_count")
            if history.get("latest_interview_ratio") is None:
                gaps.append("missing_competition_ratio")
            if not web_results:
                gaps.append("no_web_evidence")
            if len(web_search_attempts) > 0 and not web_results:
                gaps.append("web_retry_failed")

            observation = {
                "position_id": item.get("position_id"),
                "position_label": self._format_position_label(item),
                "gaps": gaps,
                "history_years": list(history.get("history_years") or []),
                "web_hit_count": len(web_results),
                "retry_count": sum(1 for attempt in web_search_attempts if attempt.get("is_retry")),
            }
            observations.append(observation)
            if gaps and retry_round < retry_budget:
                retry_targets.append(
                    {
                        "position_id": item.get("position_id"),
                        "position_label": self._format_position_label(item),
                        "gaps": gaps,
                    }
                )

        needs_retry = bool(retry_targets)
        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="observe_research_gaps",
                status="done",
                detail="宸已观察逐岗研究缺口，并判断是否需要补证重试",
                started_at=started_at,
                inputs_summary={
                    "position_research_count": len(position_researches),
                    "retry_round": retry_round,
                    "retry_budget": retry_budget,
                },
                outputs_summary={
                    "observation_count": len(observations),
                    "retry_target_count": len(retry_targets),
                    "needs_retry": needs_retry,
                },
            )
        )
        return {
            "research_observations": observations,
            "retry_targets": retry_targets,
            "needs_retry": needs_retry,
            "trace": trace,
        }

    def _node_retry_research(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        position_researches = [dict(item) for item in list(state.get("position_researches") or [])]
        retry_targets = list(state.get("retry_targets") or [])
        scope = dict(state.get("analysis_scope") or {})
        research_plan = dict(state.get("research_plan") or {})
        retry_round = int(state.get("retry_round") or 0)
        trace = list(state.get("trace") or [])

        if not retry_targets:
            trace.append(
                self._trace_entry(
                    step="retry_research",
                    status="skipped",
                    detail="没有发现必须补证的缺口，跳过重试",
                    started_at=started_at,
                    inputs_summary={"retry_round": retry_round},
                    outputs_summary={"updated_position_count": len(position_researches)},
                )
            )
            return {
                "position_researches": position_researches,
                "retry_round": retry_round,
                "needs_retry": False,
                "trace": trace,
            }

        updated_ids: set[str] = set()
        retry_trace_entries: list[dict[str, Any]] = []
        for target in retry_targets[:3]:
            position_id = str(target.get("position_id") or "").strip()
            if not position_id:
                continue
            position = next(
                (
                    item
                    for item in position_researches
                    if str(item.get("position_id") or "") == position_id
                ),
                None,
            )
            if position is None:
                continue
            history_summary = dict(position.get("history") or {})
            retry_scope = dict(scope)
            retry_scope["query"] = self._build_retry_research_query(
                position=position,
                history_summary=history_summary,
                scope=scope,
                gaps=list(target.get("gaps") or []),
            )
            web_search_result = self._search_web_evidence(
                position=position,
                history_summary=history_summary,
                scope=retry_scope,
            )
            retry_trace_entries.extend(list(web_search_result.get("trace") or []))
            merged_results = self._merge_web_result_lists(
                list(position.get("web_results") or []),
                list(web_search_result.get("results") or []),
            )
            merged_attempts = [
                *list(position.get("web_search_attempts") or []),
                *list(web_search_result.get("attempts") or []),
            ]
            position["web_results"] = merged_results
            position["web_search_attempts"] = merged_attempts
            position["analysis_text"] = self._generate_position_research_text(
                position=dict(position),
                history_summary=history_summary,
                history_records=list(position.get("history_records") or []),
                web_results=merged_results,
                web_search_attempts=merged_attempts,
                scope=retry_scope,
                research_plan=research_plan,
                policy_evidence=list(state.get("policy_evidence") or []),
            )
            updated_ids.add(position_id)

        trace.extend(retry_trace_entries)
        trace.append(
            self._trace_entry(
                step="retry_research",
                status="done",
                detail="宸已对证据缺口执行补证重试",
                started_at=started_at,
                inputs_summary={
                    "retry_round": retry_round,
                    "retry_target_count": len(retry_targets),
                },
                outputs_summary={
                    "updated_position_count": len(updated_ids),
                    "next_retry_round": retry_round + 1,
                },
            )
        )
        return {
            "position_researches": position_researches,
            "retry_round": retry_round + 1,
            "needs_retry": False,
            "trace": trace,
        }

    def _node_decide_report_focus(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        position_facts = dict(state.get("position_facts") or {})
        recommendations = list(position_facts.get("recommendations") or [])
        research_observations = list(state.get("research_observations") or [])
        position_researches = [dict(item) for item in list(state.get("position_researches") or [])]
        recommendation_by_id = {
            str(item.get("position_id") or ""): dict(item)
            for item in recommendations
            if str(item.get("position_id") or "").strip()
        }

        ranked_researches = sorted(
            position_researches,
            key=lambda item: self._rank_research_focus(item, recommendation_by_id),
            reverse=True,
        )
        report_focus_positions = [
            {
                "position_id": item.get("position_id"),
                "position_label": self._format_position_label(item),
                "score": self._rank_research_focus(item, recommendation_by_id),
                "web_hit_count": len(list(item.get("web_results") or [])),
                "history_years": list((item.get("history") or {}).get("history_years") or []),
                "gaps": next(
                    (
                        list(obs.get("gaps") or [])
                        for obs in research_observations
                        if str(obs.get("position_id") or "") == str(item.get("position_id") or "")
                    ),
                    [],
                ),
            }
            for item in ranked_researches[:6]
        ]
        focus_ids = [str(item.get("position_id") or "") for item in report_focus_positions if str(item.get("position_id") or "").strip()]
        decision_notes = [
            "优先展示历史数据更完整且补证结果更丰富的岗位。",
            "对于仍存在缺口的岗位，在报告中明确标记“无法确认”而不是补写结论。",
        ]
        if any(item.get("gaps") for item in report_focus_positions):
            decision_notes.append("存在缺口的岗位将继续保留在报告中，但不会被写成完整结论。")
        analysis_decision = {
            "focus_position_ids": focus_ids,
            "focus_positions": report_focus_positions,
            "decision_notes": decision_notes,
            "ranked_position_count": len(ranked_researches),
            "observation_count": len(research_observations),
            "search_coverage": {
                "with_web_evidence": sum(1 for item in position_researches if len(list(item.get("web_results") or [])) > 0),
                "without_web_evidence": sum(1 for item in position_researches if len(list(item.get("web_results") or [])) == 0),
            },
        }

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="decide_report_focus",
                status="done",
                detail="宸已根据观察与补证结果确定报告重点岗位",
                started_at=started_at,
                inputs_summary={
                    "observation_count": len(research_observations),
                    "recommendation_count": len(recommendations),
                },
                outputs_summary={
                    "focus_count": len(report_focus_positions),
                    "focus_ids": focus_ids[:4],
                },
            )
        )
        return {
            "analysis_decision": analysis_decision,
            "position_researches": ranked_researches,
            "trace": trace,
        }

    def _node_risk_review(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        recommendations = list(
            (state.get("position_facts") or {}).get("recommendations") or []
        )
        risk_review: dict[str, Any]

        if self.risk_review_agent is None:
            risk_review = {
                "risk_level": "low",
                "need_manual_confirm": False,
                "risk_items": [],
                "trace": [],
            }
        else:
            risk_review = self.risk_review_agent.run(
                query=str(scope.get("query") or scope.get("report_title") or ""),
                recommendations=recommendations,
            )

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="risk_review",
                status="done",
                detail="宸已完成风险复核",
                started_at=started_at,
                inputs_summary={
                    "recommendation_count": len(recommendations),
                },
                outputs_summary={
                    "risk_level": risk_review.get("risk_level"),
                    "risk_item_count": len(risk_review.get("risk_items") or []),
                },
            )
        )
        trace.extend(list(risk_review.get("trace") or []))
        return {"risk_review": risk_review, "trace": trace}

    def _node_compose_report(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        position_facts = dict(state.get("position_facts") or {})
        position_researches = list(state.get("position_researches") or [])
        research_observations = list(state.get("research_observations") or [])
        analysis_decision = dict(state.get("analysis_decision") or {})
        risk_review = dict(state.get("risk_review") or {})
        policy_evidence = list(state.get("policy_evidence") or [])
        recommendation_context = dict(state.get("recommendation_context") or {})
        recommendations = list(position_facts.get("recommendations") or [])
        trace_before_report = list(state.get("trace") or [])

        report_result = (
            self.report_generator_agent.run(
                title=str(scope.get("report_title") or "宀椾綅鍒嗘瀽鎶ュ憡"),
                recommendations=recommendations,
                risk_review=risk_review,
            )
            if self.report_generator_agent is not None
            else {
                "outline": [],
                "report": self._build_fallback_report(scope, position_facts, risk_review),
                "trace": [],
            }
        )

        report_meta = dict(report_result.get("report_meta") or {})
        outline = render_analysis_outline(scope, policy_evidence)
        report = self._append_analysis_sections(
            report=str(report_result.get("report") or ""),
            scope=scope,
            recommendation_context=recommendation_context,
            position_facts=position_facts,
            position_researches=position_researches,
            research_observations=research_observations,
            analysis_decision=analysis_decision,
            policy_evidence=policy_evidence,
            risk_review=risk_review,
            outline=outline,
            trace=[*trace_before_report, *list(report_result.get("trace") or [])],
        )
        report_meta.update(
            {
                "compose_report_length": len(report),
                "compose_outline_count": len(outline),
                "compose_used_llm": bool(report_meta.get("used_llm")),
            }
        )

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="compose_report",
                status="done",
                detail="宸已组装分析报告草稿",
                started_at=started_at,
                inputs_summary={
                "recommendation_count": len(recommendations),
                "policy_evidence_count": len(policy_evidence),
                "research_item_count": len(position_researches),
                "observation_count": len(research_observations),
            },
            outputs_summary={
                "report_length": len(report),
                "outline_count": len(outline),
            },
            )
        )
        trace.extend(list(report_result.get("trace") or []))
        return {
            "report_outline": outline,
            "report_draft": report,
            "report": report,
            "report_meta": report_meta,
            "analysis_decision": analysis_decision,
            "trace": trace,
        }

    def _node_refine_report(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        position_facts = dict(state.get("position_facts") or {})
        position_researches = list(state.get("position_researches") or [])
        policy_evidence = list(state.get("policy_evidence") or [])
        risk_review = dict(state.get("risk_review") or {})
        trace = list(state.get("trace") or [])
        draft = str(state.get("report") or state.get("report_draft") or "")
        report_meta = dict(state.get("report_meta") or {})
        cleaned = cleanup_analysis_report(draft)
        used_llm = False
        prompt_length = 0

        if self.chat_service is not None and cleaned:
            try:
                prompt = POSITION_ANALYSIS_USER_PROMPT_TEMPLATE.format(
                    analysis_goal=scope.get("analysis_goal") or "",
                    analysis_scope=_format_json_block(scope),
                    position_facts=_format_json_block(position_facts),
                    position_researches=_format_json_block(position_researches[:5]),
                    policy_evidence=_format_json_block(policy_evidence[:5]),
                    risk_review=_format_json_block(risk_review),
                    analysis_trace=_format_json_block(trace),
                    report_draft=cleaned,
                )
                prompt_length = len(prompt)
                messages = [
                    {
                        "role": "system",
                        "content": POSITION_ANALYSIS_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ]
                polished = self.chat_service.chat_completion(messages, temperature=0.2)
                polished = cleanup_analysis_report(str(polished or ""))
                if polished and len(polished) >= max(40, len(cleaned) // 2):
                    cleaned = polished
                    used_llm = True
            except Exception:
                pass

        report_meta.update(
            {
                "provider": "SiliconFlow" if self.chat_service is not None else "local",
                "model_name": self._resolve_model_name(),
                "refine_used_llm": used_llm,
                "refine_prompt_length": prompt_length,
                "refine_final_length": len(cleaned),
                "research_item_count": len(position_researches),
                "used_llm": bool(report_meta.get("used_llm")) or used_llm,
            }
        )

        trace.append(
            self._trace_entry(
                step="refine_report",
                status="done",
                detail="宸叉竻鐞嗗苟娑﹁壊鎶ュ憡鏂囨湰",
                started_at=started_at,
                inputs_summary={
                    "draft_length": len(draft),
                    "prompt_length": prompt_length,
                },
                outputs_summary={
                    "final_length": len(cleaned),
                    "used_llm": used_llm,
                    "model_name": self._resolve_model_name(),
                },
            )
        )
        return {"report": cleaned, "trace": trace, "report_meta": report_meta}

    def _node_persist_result(self, state: PositionAnalysisState) -> dict[str, Any]:
        started_at = time.perf_counter()
        scope = dict(state.get("analysis_scope") or {})
        position_facts = dict(state.get("position_facts") or {})
        position_researches = list(state.get("position_researches") or [])
        research_plan = dict(state.get("research_plan") or {})
        analysis_strategy = dict(state.get("analysis_strategy") or {})
        research_observations = list(state.get("research_observations") or [])
        analysis_decision = dict(state.get("analysis_decision") or {})
        retry_round = int(state.get("retry_round") or 0)
        retry_budget = int(state.get("retry_budget") or 0)
        policy_evidence = list(state.get("policy_evidence") or [])
        risk_review = dict(state.get("risk_review") or {})
        recommendation_context = dict(state.get("recommendation_context") or {})
        report = str(state.get("report") or "")
        report_meta = dict(state.get("report_meta") or {})
        needs_more_info = bool(state.get("needs_more_info"))
        missing_fields = list(state.get("missing_fields") or [])
        clarifying_questions = list(state.get("clarifying_questions") or [])
        clarification_reason = str(state.get("clarification_reason") or "")
        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="persist_result",
                status="done",
                detail="宸插噯澶囨寔涔呭寲鍒嗘瀽缁撴灉" if not needs_more_info else "宸插噯澶囨寔涔呭寲杩介棶缁撴灉",
                started_at=started_at,
                inputs_summary={
                    "report_length": len(report),
                    "policy_evidence_count": len(policy_evidence),
                },
                outputs_summary={
                    "status": "needs_more_info" if needs_more_info else "completed",
                    "stage": "clarify_requirements" if needs_more_info else "persist_result",
                },
                evidence_refs=[
                    _build_evidence_ref(item) for item in policy_evidence[:5]
                ],
            )
        )
        output_json = {
            "snapshot": dict(state.get("normalized_snapshot") or {}),
            "analysis_scope": dict(scope),
            "recommendation_context": recommendation_context,
            "position_facts": {
                "summary": dict(position_facts.get("summary") or {}),
                "recommendation_count": len(position_facts.get("recommendations") or []),
                "selected_positions": list(position_facts.get("selected_positions") or []),
                "recommendations": list(position_facts.get("recommendations") or []),
            },
            "policy_evidence": [
                _build_evidence_ref(item) for item in policy_evidence
            ],
            "risk_review": {
                "risk_level": risk_review.get("risk_level"),
                "need_manual_confirm": bool(risk_review.get("need_manual_confirm", False)),
                "risk_item_count": len(risk_review.get("risk_items") or []),
            },
            "analysis_meta": report_meta,
            "research_plan": research_plan,
            "analysis_strategy": analysis_strategy,
            "research_observations": research_observations,
            "analysis_decision": analysis_decision,
            "retry_state": {
                "retry_round": retry_round,
                "retry_budget": retry_budget,
                "needs_retry": bool(state.get("needs_retry")),
            },
            "position_researches": [
                {
                    "index": item.get("index"),
                    "position_id": item.get("position_id"),
                    "department_name": item.get("department_name"),
                    "office_name": item.get("office_name"),
                    "job_title": item.get("job_title"),
                    "position_code": item.get("position_code"),
                    "history": dict(item.get("history") or {}),
                    "history_records": list(item.get("history_records") or []),
                    "web_results": list(item.get("web_results") or []),
                    "web_search_attempts": list(item.get("web_search_attempts") or []),
                    "analysis_text": str(item.get("analysis_text") or ""),
                    "research_plan": dict(item.get("research_plan") or {}),
                }
                for item in position_researches
            ],
            "report_outline": list(state.get("report_outline") or []),
            "needs_more_info": needs_more_info,
            "missing_fields": missing_fields,
            "clarifying_questions": clarifying_questions,
            "clarification_reason": clarification_reason,
            "analysis_journey": self._build_analysis_journey(
                trace=trace,
                recommendation_context=recommendation_context,
                position_researches=position_researches,
                analysis_strategy=analysis_strategy,
                research_observations=research_observations,
                analysis_decision=analysis_decision,
                risk_review=risk_review,
            ),
            "agent_journey": [self._trace_brief(item) for item in trace],
            "trace_count": len(trace),
        }
        return {
            "status": "needs_more_info" if needs_more_info else "completed",
            "stage": "clarify_requirements" if needs_more_info else "persist_result",
            "report": report,
            "trace": trace,
            "output_json": output_json,
            "analysis_scope": scope,
            "position_facts": position_facts,
            "policy_evidence": policy_evidence,
            "position_researches": position_researches,
            "research_plan": research_plan,
            "analysis_strategy": analysis_strategy,
            "recommendation_context": recommendation_context,
            "risk_review": risk_review,
            "report_outline": list(state.get("report_outline") or []),
            "needs_more_info": needs_more_info,
            "missing_fields": missing_fields,
            "clarifying_questions": clarifying_questions,
            "clarification_reason": clarification_reason,
            "task_id": state.get("task_id"),
            "snapshot_id": state.get("snapshot_id"),
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

    def _search_web_evidence(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        scope: dict[str, Any],
        planned_queries: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.web_search_service is None:
            return {"results": [], "attempts": [], "trace": []}

        queries = self._build_web_search_queries(
            position=position,
            history_summary=history_summary,
            scope=scope,
        )
        queries = _dedupe_text_list([
            *(list(planned_queries or [])),
            *queries,
        ])
        results: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for query_index, query in enumerate(queries[:3], start=1):
            query_attempts = [query]
            retry_query = self._build_web_retry_query(query)
            if retry_query and retry_query != query:
                query_attempts.append(retry_query)

            for attempt_index, current_query in enumerate(query_attempts, start=1):
                attempt_started = time.perf_counter()
                hits = self.web_search_service.search(current_query, top_k=3)
                attempt_results: list[dict[str, Any]] = []
                browser_fallback_count = 0
                fetched_count = 0
                for hit in hits:
                    url = str(hit.get("url") or "").strip()
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    fetched = self._fetch_web_page(url)
                    fetched_count += 1
                    browser_result = {}
                    if self._needs_browser_fallback(fetched):
                        browser_result = self._read_with_browser(url)
                        if browser_result:
                            browser_fallback_count += 1
                    merged_content = self._merge_web_content(hit, fetched, browser_result)
                    attempt_results.append(
                        {
                            "query": current_query,
                            "title": hit.get("title"),
                            "url": hit.get("url"),
                            "snippet": hit.get("snippet"),
                            "source": hit.get("source") or "web",
                            "content": merged_content.get("content"),
                            "content_type": merged_content.get("content_type"),
                            "retrieved_via": merged_content.get("retrieved_via"),
                            "final_url": merged_content.get("final_url"),
                            "is_pdf": merged_content.get("is_pdf", False),
                            "attempt_index": attempt_index,
                            "query_index": query_index,
                        }
                    )
                results.extend(attempt_results)
                attempts.append(
                    {
                        "query": current_query,
                        "query_index": query_index,
                        "attempt_index": attempt_index,
                        "hit_count": len(attempt_results),
                        "fetched_count": fetched_count,
                        "browser_fallback_count": browser_fallback_count,
                        "is_retry": attempt_index > 1,
                    }
                )
                trace.append(
                    self._trace_entry(
                        step="web_search_attempt",
                        status="done" if attempt_results else "retry",
                        detail=(
                            f"岗位 {self._format_position_label(position)} 的外网检索"
                            f"（第 {query_index} 个查询，第 {attempt_index} 次尝试）"
                        ),
                        started_at=attempt_started,
                        inputs_summary={
                            "query": current_query,
                            "query_index": query_index,
                            "attempt_index": attempt_index,
                        },
                        outputs_summary={
                            "hit_count": len(attempt_results),
                            "fetched_count": fetched_count,
                            "browser_fallback_count": browser_fallback_count,
                        },
                    )
                )
                if attempt_results:
                    break
        return {
            "results": results[:5],
            "attempts": attempts,
            "trace": trace,
        }

    def _fetch_web_page(self, url: str) -> dict[str, Any]:
        if self.web_fetch_service is None or not url:
            return {}
        return dict(self.web_fetch_service.fetch(url) or {})

    def _read_with_browser(self, url: str) -> dict[str, Any]:
        if self.browser_service is None or not url:
            return {}
        return dict(self.browser_service.read(url) or {})

    def _needs_browser_fallback(self, fetched: dict[str, Any]) -> bool:
        if not fetched:
            return False
        text = str(fetched.get("text") or "").strip()
        if not text:
            return True
        if len(text) < 200 and not bool(fetched.get("is_pdf")):
            return True
        content_type = str(fetched.get("content_type") or "").lower()
        return "html" in content_type and "rendered" not in str(
            fetched.get("retrieved_via") or ""
        )

    def _merge_web_content(
        self,
        hit: dict[str, Any],
        fetched: dict[str, Any],
        browser_result: dict[str, Any],
    ) -> dict[str, Any]:
        browser_text = str(browser_result.get("text") or "").strip()
        fetched_text = str(fetched.get("text") or "").strip()
        content = browser_text or fetched_text or str(hit.get("snippet") or "").strip()
        retrieved_via = (
            browser_result.get("retrieved_via")
            or fetched.get("retrieved_via")
            or hit.get("source")
            or "web"
        )
        title = (
            browser_result.get("title")
            or fetched.get("title")
            or hit.get("title")
            or ""
        )
        return {
            "content": content,
            "content_type": browser_result.get("content_type")
            or fetched.get("content_type"),
            "retrieved_via": retrieved_via,
            "final_url": browser_result.get("url")
            or fetched.get("final_url")
            or hit.get("url"),
            "title": title,
            "is_pdf": bool(fetched.get("is_pdf")),
        }

    def _generate_position_research_text(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]],
        web_results: list[dict[str, Any]],
        web_search_attempts: list[dict[str, Any]],
        scope: dict[str, Any],
        research_plan: dict[str, Any],
        policy_evidence: list[dict[str, Any]],
    ) -> str:
        position_fact = {
            key: position.get(key)
            for key in (
                "department_name",
                "office_name",
                "job_title",
                "position_code",
                "work_location",
                "education_requirement",
                "degree_requirement",
                "major_requirement",
                "political_status_requirement",
                "recruit_count",
                "interview_ratio",
                "remarks",
            )
        }
        scaffold = self._build_position_research_scaffold(
            position=position_fact,
            history_summary=history_summary,
            history_records=history_records,
            web_results=web_results,
            web_search_attempts=web_search_attempts,
        )
        if self.chat_service is None:
            fallback = self._build_position_research_fallback(
                position=position_fact,
                history_summary=history_summary,
                history_records=history_records,
                web_results=web_results,
            )
            return cleanup_analysis_report("\n".join([scaffold, "", fallback]))

        prompt = POSITION_RESEARCH_USER_PROMPT_TEMPLATE.format(
            analysis_goal=scope.get("analysis_goal") or "",
            research_plan=_format_json_block(research_plan),
            position_fact=_format_json_block(position_fact),
            history_summary=_format_json_block(history_summary),
            history_records=_format_json_block(history_records[:5]),
            web_results=_format_json_block(web_results[:5]),
            policy_evidence=_format_json_block(policy_evidence[:5]),
            profile=_format_json_block(scope.get("profile_summary") or {}),
        )
        messages = [
            {"role": "system", "content": POSITION_RESEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            response = self.chat_service.chat_completion(messages, temperature=0.2)
            model_text = cleanup_analysis_report(str(response or ""))
            if model_text:
                return cleanup_analysis_report(
                    "\n".join(
                        [
                            scaffold,
                            "",
                            "#### 模型补充分析",
                            model_text,
                        ]
                    )
                )
            return scaffold
        except Exception:
            fallback = self._build_position_research_fallback(
                position=position_fact,
                history_summary=history_summary,
                history_records=history_records,
                web_results=web_results,
            )
            return cleanup_analysis_report("\n".join([scaffold, "", fallback]))

    def _build_position_research_scaffold(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]],
        web_results: list[dict[str, Any]],
        web_search_attempts: list[dict[str, Any]],
    ) -> str:
        title = " / ".join(
            part
            for part in [
                str(position.get("department_name") or "").strip(),
                str(position.get("office_name") or "").strip(),
                str(position.get("job_title") or "").strip(),
            ]
            if part
        ) or "未知岗位"
        years = [
            str(record.get("year"))
            for record in history_records
            if record.get("year") is not None
        ]
        recent_notes = list(history_summary.get("notes") or [])[:3]
        retry_count = sum(1 for item in web_search_attempts if item.get("is_retry"))
        lines = [
            f"### {title}",
            "",
            "#### 事实核对",
            f"- 历史记录条数：{history_summary.get('record_count', 0)}",
            f"- 历史年份：{('、'.join(years) if years else '未检索到')}",
            f"- 最近一期招录：{history_summary.get('latest_recruit_count') or '未检索到'}",
            f"- 最近一期报录比：{history_summary.get('latest_interview_ratio') or '未检索到'}",
            f"- 外网补证结果：{len(web_results)} 条",
            f"- 检索重试次数：{retry_count} 次",
        ]
        if recent_notes:
            lines.append("- 历史趋势提示：")
            for note in recent_notes:
                lines.append(f"  - {note}")
        if history_records:
            lines.append(" ")
            lines.append("#### 历史记录摘录")
            for record in history_records[:3]:
                lines.append(
                    f"- {record.get('year') or '未知年份'}年："
                    f"招录 {record.get('recruit_count') or '未公开'}，"
                    f"报录比 {record.get('interview_ratio') or '未公开'}"
                )
        if web_results:
            lines.append(" ")
            lines.append("#### 外网补证摘录")
            for item in web_results[:3]:
                title_text = str(item.get("title") or "").strip()
                snippet = str(item.get("snippet") or "").strip()
                if title_text:
                    lines.append(f"- {title_text}: {snippet[:120]}")
        return cleanup_analysis_report("\n".join(lines))

    def _build_web_retry_query(self, query: str) -> str | None:
        tokens = [token for token in re.split(r"\s+", str(query or "").strip()) if token]
        if len(tokens) <= 3:
            return None
        filtered = [
            token
            for token in tokens
            if token not in {"历年", "招录人数", "报录比", "招考简章", "官方公告"}
            and not re.fullmatch(r"\d{4}", token)
        ]
        if len(filtered) >= len(tokens):
            filtered = tokens[:-2]
        narrowed = " ".join(filtered).strip()
        return narrowed or None

    def _build_position_research_fallback(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]],
        web_results: list[dict[str, Any]],
    ) -> str:
        title = " / ".join(
            part
            for part in [
                str(position.get("department_name") or "").strip(),
                str(position.get("office_name") or "").strip(),
                str(position.get("job_title") or "").strip(),
            ]
            if part
        ) or "鏈煡宀椾綅"
        lines = [f"### {title}", "", "#### 宀椾綅缁撹"]
        lines.append("- 先看硬条件是否匹配，再看历史招录和竞争强度。")
        lines.append("")
        lines.append("#### 鍘嗗彶鎷涘綍瓒嬪娍")
        if history_records:
            for record in history_records[:5]:
                year = record.get("year") or "鏈煡骞翠唤"
                recruit = record.get("recruit_count") or "鏈～"
                ratio = record.get("interview_ratio") or "鏈～"
                lines.append(f"- {year}: 鎷涘綍浜烘暟 {recruit}锛屾姤褰曟瘮 {ratio}")
        else:
            lines.append("- 本地岗位库暂未找到可用于趋势判断的历史记录。")
        if history_summary.get("notes"):
            for note in list(history_summary.get("notes") or [])[:3]:
                lines.append(f"- {note}")
        lines.append("")
        lines.append("#### 绔炰簤寮哄害鍒ゆ柇")
        lines.append(
            f"- 趋势判断：{history_summary.get('recruit_count_trend', 'unknown')} / {history_summary.get('interview_ratio_trend', 'unknown')}"
        )
        lines.append("")
        lines.append("")
        lines.append("#### 政策与资格风险")
        lines.append("- 重点核对专业、学历、学位、政治面貌和备注中的隐性要求。")
        if web_results:
            lines.append("")
            lines.append("#### 璇佹嵁鏉ユ簮")
            for item in web_results[:3]:
                title_text = str(item.get("title") or "").strip()
                snippet = str(item.get("snippet") or "").strip()
                if title_text:
                    lines.append(f"- {title_text}: {snippet[:120]}")
        lines.append("")
        lines.append("#### 鎺ㄨ崘缁撹")
        lines.append("- 适合程度需要结合你的专业和历史竞争强度进一步确认。")
        return cleanup_analysis_report("\n".join(lines))

    def _build_web_search_queries(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        scope: dict[str, Any],
    ) -> list[str]:
        department_name = str(position.get("department_name") or "").strip()
        office_name = str(position.get("office_name") or "").strip()
        job_title = str(position.get("job_title") or "").strip()
        position_code = str(position.get("position_code") or "").strip()
        year = str(scope.get("year") or "").strip()
        scope_query = str(scope.get("query") or "").strip()
        queries = [
            " ".join(
                part
                for part in [
                    scope_query,
                    department_name,
                    office_name,
                    job_title,
                    position_code,
                ]
                if part
            ).strip(),
            " ".join(
                part
                for part in [
                    department_name,
                    office_name,
                    job_title,
                    position_code,
                    "鍘嗗勾",
                    "鎷涘綍浜烘暟",
                    "报录比",
                ]
                if part
            ).strip(),
            " ".join(
                part
                for part in [
                    department_name,
                    job_title,
                    year,
                    "招考简章",
                    "鎷涘綍浜烘暟",
                ]
                if part
            ).strip(),
        ]
        if history_summary.get("record_count", 0) == 0:
            queries.append(
                " ".join(
                    part
                    for part in [
                        department_name,
                        office_name,
                        job_title,
                        "报录比",
                        "瀹樻柟鍏憡",
                    ]
                    if part
                ).strip()
            )
        return [query for query in queries if query]

    def _build_web_research_targets(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]],
        scope: dict[str, Any],
        strategy_target: dict[str, Any],
    ) -> list[dict[str, Any]]:
        llm_targets = self._plan_web_research_targets_llm(
            position=position,
            history_summary=history_summary,
            history_records=history_records,
            scope=scope,
            strategy_target=strategy_target,
        )
        if llm_targets:
            return llm_targets

        position_label = self._format_position_label(position)
        fallback_year = str(scope.get("year") or "").strip()
        targets: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for record in sorted(
            history_records,
            key=lambda item: self._extract_record_year(item) or 0,
            reverse=True,
        ):
            year = self._extract_record_year(record)
            year_text = str(year or fallback_year or "").strip()
            missing_fields: list[str] = []
            if self._is_missing_recruit_count(record):
                missing_fields.append("recruit_count")
            if self._is_missing_interview_ratio(record):
                missing_fields.append("interview_ratio")

            for missing_field in missing_fields:
                key = f"{year_text}:{missing_field}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                targets.append(
                    {
                        "year": year_text,
                        "missing_field": missing_field,
                        "position_label": position_label,
                        "queries": self._build_queries_for_missing_field(
                            position_label=position_label,
                            year=year_text,
                            missing_field=missing_field,
                        ),
                        "focus": self._missing_field_focus(missing_field, year_text),
                        "priority": "high" if missing_field == "interview_ratio" else "medium",
                    }
                )

        if not targets and history_summary.get("record_count", 0) == 0:
            targets.append(
                {
                    "year": fallback_year,
                    "missing_field": "history_sparse",
                    "position_label": position_label,
                    "queries": self._build_queries_for_missing_field(
                        position_label=position_label,
                        year=fallback_year,
                        missing_field="history_sparse",
                    ),
                    "focus": [
                        "官方公告",
                        "招考简章",
                        "招录人数",
                        "报录比",
                        "进面分",
                    ],
                    "priority": "high",
                }
            )

        if strategy_target.get("needs_web_search", True) and strategy_target.get(
            "search_queries"
        ):
            targets.append(
                {
                    "year": fallback_year,
                    "missing_field": "strategy_hint",
                    "position_label": position_label,
                    "queries": [
                        str(query).strip()
                        for query in list(strategy_target.get("search_queries") or [])
                        if str(query).strip()
                    ],
                    "focus": list(strategy_target.get("focus") or []),
                    "priority": "medium",
                }
            )

        return targets

    def _plan_web_research_targets_llm(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        history_records: list[dict[str, Any]],
        scope: dict[str, Any],
        strategy_target: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self.chat_service is None:
            return []

        payload = {
            "position": {
                "department_name": position.get("department_name"),
                "office_name": position.get("office_name"),
                "job_title": position.get("job_title"),
                "position_code": position.get("position_code"),
                "work_location": position.get("work_location"),
                "remarks": position.get("remarks"),
            },
            "history_summary": {
                "record_count": history_summary.get("record_count"),
                "history_years": history_summary.get("history_years"),
                "latest_recruit_count": history_summary.get("latest_recruit_count"),
                "latest_interview_ratio": history_summary.get("latest_interview_ratio"),
                "recruit_count_trend": history_summary.get("recruit_count_trend"),
                "interview_ratio_trend": history_summary.get("interview_ratio_trend"),
                "notes": list(history_summary.get("notes") or []),
            },
            "history_records": [
                {
                    "year": record.get("year"),
                    "recruit_count": record.get("recruit_count"),
                    "interview_ratio": record.get("interview_ratio"),
                    "interview_score": record.get("interview_score"),
                    "remarks": record.get("remarks"),
                }
                for record in history_records[:6]
            ],
            "strategy_target": {
                "index": strategy_target.get("index"),
                "history_priority": strategy_target.get("history_priority"),
                "needs_web_search": strategy_target.get("needs_web_search"),
                "focus": list(strategy_target.get("focus") or []),
                "search_queries": list(strategy_target.get("search_queries") or []),
                "retry_queries": list(strategy_target.get("retry_queries") or []),
            },
            "analysis_scope": {
                "year": scope.get("year"),
                "analysis_goal": scope.get("analysis_goal"),
                "query": scope.get("query"),
            },
        }
        prompt = (
            "你是岗位外网补证规划器。先判断这条岗位历史数据里缺少什么，再生成最少量、最具体的搜索目标。\n"
            "要求：\n"
            "1. 只为缺失、冲突、或明显不完整的信息创建 target。\n"
            "2. 每个 target 只覆盖一个缺口，禁止把招录人数、报录比、进面分、公告、面试名单混在一起。\n"
            "3. 如果 2025 缺少进面数据，就单独创建 2025 + interview_score/进面分 的 target；如果 2024 缺少报录比，就单独创建 2024 + interview_ratio/报录比 的 target。\n"
            "4. search_queries 必须短、窄、可验证，优先面向具体年份和具体缺口。\n"
            "5. 如果没有值得外网补证的缺口，返回空数组。\n"
            "6. 输出必须是严格 JSON，不要 Markdown，不要解释，不要代码块。\n"
            'JSON 格式：{"summary":"...","targets":[{"year":"2025","missing_field":"interview_score","needs_web_search":true,"priority":"high","focus":["..."],"search_queries":["..."],"retry_queries":["..."],"observation_questions":["..."],"evidence_focus":["..."],"reason":"..."}]}\n'
            f"{_format_json_block(payload)}"
        )
        messages = [
            {"role": "system", "content": POSITION_STRATEGY_PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = self.chat_service.chat_completion(messages, temperature=0.2)
            parsed = _extract_json_object(str(raw or ""))
            if not isinstance(parsed, dict):
                return []
            targets = parsed.get("targets")
            if not isinstance(targets, list):
                return []
            normalized_targets: list[dict[str, Any]] = []
            for item in targets:
                normalized = self._normalize_web_research_target(
                    item,
                    position_label=self._format_position_label(position),
                    fallback_year=str(scope.get("year") or "").strip(),
                )
                if normalized is not None:
                    normalized_targets.append(normalized)
            return self._dedupe_research_targets(normalized_targets)
        except Exception:
            return []

    def _normalize_web_research_target(
        self,
        item: Any,
        *,
        position_label: str,
        fallback_year: str,
    ) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        year = str(item.get("year") or fallback_year or "").strip()
        missing_field = str(item.get("missing_field") or "").strip()
        if not year and not missing_field:
            return None

        normalized: dict[str, Any] = {
            "year": year,
            "missing_field": missing_field or "history_sparse",
            "position_label": position_label,
        }
        for key in ("priority", "reason"):
            value = item.get(key)
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, "", [], {}):
                normalized[key] = value

        for key in (
            "focus",
            "search_queries",
            "retry_queries",
            "observation_questions",
            "evidence_focus",
        ):
            values = item.get(key)
            if isinstance(values, list):
                normalized[key] = _dedupe_text_list(
                    [str(entry).strip() for entry in values if str(entry).strip()]
                )

        if not normalized.get("search_queries"):
            normalized["search_queries"] = self._build_queries_for_missing_field(
                position_label=position_label,
                year=year,
                missing_field=str(normalized.get("missing_field") or ""),
            )
        if not normalized.get("focus"):
            normalized["focus"] = self._missing_field_focus(
                str(normalized.get("missing_field") or ""),
                year,
            )
        if not normalized.get("retry_queries"):
            normalized["retry_queries"] = list(normalized.get("search_queries") or [])
        if not normalized.get("observation_questions"):
            normalized["observation_questions"] = [
                f"这个岗位在 {year} 年是否存在 {normalized.get('missing_field') or '缺口'} 的可核验证据？"
            ]
        if not normalized.get("evidence_focus"):
            normalized["evidence_focus"] = list(normalized.get("focus") or [])

        normalized["needs_web_search"] = bool(
            item.get("needs_web_search", True)
            or normalized.get("search_queries")
        )
        return normalized

    def _dedupe_research_targets(
        self,
        targets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for target in targets:
            year = str(target.get("year") or "").strip()
            missing_field = str(target.get("missing_field") or "").strip()
            key = f"{year}:{missing_field}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(target)
        return deduped

    def _build_queries_for_missing_field(
        self,
        *,
        position_label: str,
        year: str,
        missing_field: str,
    ) -> list[str]:
        queries: list[str] = []
        if missing_field == "recruit_count":
            queries.append(
                " ".join(
                    part
                    for part in [
                        position_label,
                        year,
                        "招录人数",
                        "招考简章",
                        "官方公告",
                    ]
                    if part
                ).strip()
            )
        elif missing_field == "interview_ratio":
            queries.append(
                " ".join(
                    part
                    for part in [
                        position_label,
                        year,
                        "报录比",
                        "进面分",
                        "面试名单",
                        "官方公告",
                    ]
                    if part
                ).strip()
            )
        elif missing_field == "interview_score":
            queries.append(
                " ".join(
                    part
                    for part in [
                        position_label,
                        year,
                        "最低进面分",
                        "面试分数线",
                        "进面名单",
                    ]
                    if part
                ).strip()
            )
        elif missing_field == "history_sparse":
            queries.append(
                " ".join(
                    part
                    for part in [
                        position_label,
                        year,
                        "历年招录",
                        "招录人数",
                        "报录比",
                        "进面分",
                    ]
                    if part
                ).strip()
            )
        else:
            queries.append(
                " ".join(
                    part
                    for part in [
                        position_label,
                        year,
                        "招录人数",
                        "报录比",
                    ]
                    if part
                ).strip()
            )
        return [query for query in queries if query]

    def _missing_field_focus(self, missing_field: str, year_text: str) -> list[str]:
        if missing_field == "recruit_count":
            return [f"{year_text}年招录人数", "招录公告", "官方公告"]
        if missing_field == "interview_ratio":
            return [f"{year_text}年报录比", "进面分", "面试名单", "官方公告"]
        if missing_field == "interview_score":
            return [f"{year_text}年最低进面分", "面试分数线", "进面名单"]
        if missing_field == "history_sparse":
            return ["历年招录", "报录比", "进面分", "官方公告"]
        return ["官方公告", "招考简章"]

    def _extract_record_year(self, record: dict[str, Any]) -> int | None:
        raw_year = record.get("year")
        if isinstance(raw_year, int):
            return raw_year
        if isinstance(raw_year, float) and raw_year.is_integer():
            return int(raw_year)
        match = re.search(r"(20\\d{2})", str(raw_year or ""))
        return int(match.group(1)) if match else None

    def _is_missing_recruit_count(self, record: dict[str, Any]) -> bool:
        value = record.get("recruit_count")
        if value is None:
            return True
        text = str(value).strip()
        return text in {"", "-", "--", "缺失", "未知", "暂无"}

    def _is_missing_interview_ratio(self, record: dict[str, Any]) -> bool:
        value = record.get("interview_ratio")
        if value is None:
            return True
        text = str(value).strip()
        if text in {"", "-", "--", "缺失", "未知", "暂无"}:
            return True
        return not bool(re.search(r"\\d", text))

    def _build_retry_research_query(
        self,
        *,
        position: dict[str, Any],
        history_summary: dict[str, Any],
        scope: dict[str, Any],
        gaps: list[str],
    ) -> str:
        title_parts = [
            str(position.get("department_name") or "").strip(),
            str(position.get("office_name") or "").strip(),
            str(position.get("job_title") or "").strip(),
            str(position.get("position_code") or "").strip(),
        ]
        gap_terms: list[str] = []
        if "missing_recruit_count" in gaps:
            gap_terms.append("招录人数")
        if "missing_competition_ratio" in gaps:
            gap_terms.append("报录比")
        if "no_web_evidence" in gaps or "web_retry_failed" in gaps:
            gap_terms.extend(["官方公告", "招考简章"])
        if "history_sparse" in gaps:
            gap_terms.extend(["历年", "历史数据", "进面分数"])
        if history_summary.get("record_count", 0) == 0:
            gap_terms.append("历年招录")
        scope_year = str(scope.get("year") or "").strip()
        if scope_year:
            gap_terms.append(scope_year)
        query = " ".join(part for part in [*title_parts, *gap_terms] if part)
        return query.strip()

    def _merge_web_result_lists(
        self,
        existing: list[dict[str, Any]],
        new_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in [*existing, *new_items]:
            key = (
                str(item.get("final_url") or item.get("url") or "").strip(),
                str(item.get("content") or item.get("snippet") or "").strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged[:8]

    def _rank_research_focus(
        self,
        item: dict[str, Any],
        recommendation_by_id: dict[str, dict[str, Any]],
    ) -> float:
        history = dict(item.get("history") or {})
        web_results = list(item.get("web_results") or [])
        web_search_attempts = list(item.get("web_search_attempts") or [])
        recommendation = recommendation_by_id.get(str(item.get("position_id") or ""))
        score = 0.0
        score += float(recommendation.get("score") or 0.0) if recommendation else 0.0
        score += min(len(web_results), 5) * 6.0
        score += min(len(list(history.get("history_years") or [])), 3) * 4.0
        if history.get("latest_recruit_count") is not None:
            score += 5.0
        if history.get("latest_interview_ratio") is not None:
            score += 5.0
        if any(attempt.get("is_retry") for attempt in web_search_attempts):
            score += 3.0
        if str(item.get("risk_level") or "").lower() == "high":
            score -= 5.0
        if bool(item.get("need_manual_confirm")):
            score -= 2.0
        return score

    def _build_observation_lines(
        self,
        research_observations: list[dict[str, Any]],
        analysis_decision: dict[str, Any],
    ) -> list[str]:
        if not research_observations:
            return ["- 暂无观察结果，无法评估缺口。"]

        lines = [
            f"- 已观察岗位数: {len(research_observations)}",
            f"- 重点岗位数: {len(list(analysis_decision.get('focus_positions') or []))}",
        ]
        gap_counter: Counter[str] = Counter()
        for item in research_observations:
            gap_counter.update(list(item.get("gaps") or []))
        if gap_counter:
            lines.append(
                "- 主要缺口: "
                + "，".join(f"{key} {count} 项" for key, count in gap_counter.most_common(5))
            )
        else:
            lines.append("- 观察结果显示当前候选岗位的历史与补证覆盖较完整。")

        decision_notes = list(analysis_decision.get("decision_notes") or [])
        if decision_notes:
            lines.append("- 决策说明:")
            for note in decision_notes[:4]:
                lines.append(f"  - {note}")
        coverage = dict(analysis_decision.get("search_coverage") or {})
        if coverage:
            lines.append(
                f"- 搜索覆盖: 有证据 {coverage.get('with_web_evidence', 0)} 条，"
                f"无证据 {coverage.get('without_web_evidence', 0)} 条"
            )
        return lines

    def _build_web_search_summary_lines(
        self,
        position_researches: list[dict[str, Any]],
    ) -> list[str]:
        if not position_researches:
            return ["- 暂无外网补证记录。"]

        lines: list[str] = []
        for item in position_researches[:5]:
            title = self._format_position_label(item)
            web_results = list(item.get("web_results") or [])
            web_search_attempts = list(item.get("web_search_attempts") or [])
            retry_count = sum(1 for attempt in web_search_attempts if attempt.get("is_retry"))
            top_titles = [
                str(result.get("title") or result.get("source") or "").strip()
                for result in web_results[:3]
                if str(result.get("title") or result.get("source") or "").strip()
            ]
            summary = "；".join(top_titles) if top_titles else "未检索到有效网页正文"
            lines.append(
                f"- {title}: 外网命中 {len(web_results)} 条，重试 {retry_count} 次，主要来源 {summary}"
            )
        return lines

    def _append_analysis_sections(
        self,
        *,
        report: str,
        scope: dict[str, Any],
        recommendation_context: dict[str, Any],
        position_facts: dict[str, Any],
        position_researches: list[dict[str, Any]],
        research_observations: list[dict[str, Any]],
        analysis_decision: dict[str, Any],
        policy_evidence: list[dict[str, Any]],
        risk_review: dict[str, Any],
        outline: list[str],
        trace: list[dict[str, Any]],
    ) -> str:
        summary = dict(position_facts.get("summary") or {})
        selected_positions = list(position_facts.get("selected_positions") or [])
        recommendations = list(position_facts.get("recommendations") or [])
        profile = dict(scope.get("profile_summary") or scope.get("effective_profile") or {})

        lines = [report.strip()] if report.strip() else []
        if lines:
            lines.append("")

        recommendation_context_lines = self._build_recommendation_context_lines(
            recommendation_context
        )
        lines.extend(
            [
                "## 前置推荐与规划",
                *recommendation_context_lines,
                "",
                "## 用户画像摘要",
                *self._build_user_profile_lines(profile),
                "",
                "## 候选岗位池概览",
                *self._build_candidate_pool_lines(
                    selected_positions=selected_positions,
                    recommendations=recommendations,
                    summary=summary,
                ),
                "",
                "## 推荐结论总览",
                *self._build_recommendation_summary_lines(recommendations),
                "",
                "## Agent 观察与决策",
                *self._build_observation_lines(research_observations, analysis_decision),
                "",
                "## 2024-2026 年招录人数对比",
                *self._build_history_trend_lines_v2(position_researches),
                "",
                "## 报录比 / 竞争比分析",
                *self._build_competition_lines_v2(position_researches),
                "",
                "## 进面分数分析",
                *self._build_score_lines_v2(position_researches),
                "",
                "## 外网补证摘要",
                *self._build_web_search_summary_lines(position_researches),
                "",
                "## 重点岗位逐项分析",
            ]
        )
        if position_researches:
            for index, item in enumerate(position_researches[:10], start=1):
                lines.extend(self._build_position_analysis_block_v2(index, item))
        else:
            lines.append("- 暂无可用于逐项分析的岗位。")

        lines.extend(
            [
                "",
                "## 政策证据",
            ]
        )
        if policy_evidence:
            for item in policy_evidence[:5]:
                doc_title = str(item.get("doc_title") or item.get("source_file") or "鏈煡鏉ユ簮")
                content = str(item.get("content") or "").strip()
                lines.append(f"- {doc_title}: {content[:120]}")
        else:
            lines.append("- 当前本地岗位库还没有足够的历史记录可用于趋势判断。")

        lines.append("")
        lines.append("## 风险提示")
        if risk_review.get("risk_items"):
            for item in list(risk_review.get("risk_items") or [])[:5]:
                lines.append(
                    "- "
                    f"{item.get('risk_type')}: "
                    f"{item.get('explanation') or item.get('evidence') or '闇€澶嶆牳'}"
                )
        else:
            lines.append("- 暂未识别到明显风险。")

        lines.extend(
            [
                "",
                "## 岗位横向对比表",
                *self._build_comparison_table_lines_v2(recommendations or selected_positions),
                "",
                "## 报名注意事项",
                *self._build_registration_notes_lines_v2(
                    selected_positions=selected_positions,
                    risk_review=risk_review,
                ),
                "",
                "## 最终报考建议",
                *self._build_final_advice_lines_v2(
                    recommendations=recommendations,
                    selected_positions=selected_positions,
                    risk_review=risk_review,
                ),
                "",
                "## 下一步",
                "- 先核对硬性条件，再决定是否继续投递。",
                "- 若有人工核实要求，优先回看原始公告或政策原文。",
            ]
        )
        if outline:
            lines.append("")
            lines.append("## 报告提纲")
            for item in outline:
                lines.append(f"- {item}")

        if trace:
            lines.append("")
            lines.append("## Agent 轨迹摘要")
            for item in trace[-10:]:
                step = str(item.get("step") or "unknown_step")
                status = str(item.get("status") or "done")
                detail = str(item.get("detail") or "")
                outputs = dict(item.get("outputs_summary") or {})
                summary_bits: list[str] = []
                for key in (
                    "needs_more_info",
                    "question_count",
                    "evidence_query_count",
                    "evidence_hit_count",
                    "risk_level",
                    "final_length",
                ):
                    if key in outputs:
                        summary_bits.append(f"{key}={outputs.get(key)}")
                suffix = f" | {'; '.join(summary_bits)}" if summary_bits else ""
                lines.append(f"- {step} ({status})：{detail}{suffix}")

        return cleanup_analysis_report("\n".join(lines))

    def _build_analysis_journey(
        self,
        *,
        trace: list[dict[str, Any]],
        recommendation_context: dict[str, Any],
        position_researches: list[dict[str, Any]],
        analysis_strategy: dict[str, Any],
        research_observations: list[dict[str, Any]],
        analysis_decision: dict[str, Any],
        risk_review: dict[str, Any],
    ) -> list[dict[str, Any]]:
        journey: list[dict[str, Any]] = []
        if recommendation_context:
            recommendations = list(recommendation_context.get("recommendations") or [])
            journey.append(
                {
                    "phase": "recommend",
                    "step": "ingest_recommendation_context",
                    "status": "done",
                    "detail": "先接收推荐 Agent 产出的规划上下文，再开始岗位分析。",
                    "elapsed_ms": 0,
                    "summary_lines": [
                        f"推荐数: {len(recommendations)}",
                        f"状态: {recommendation_context.get('status') or 'completed'}",
                    ],
                }
            )
        summary_lines = list(analysis_strategy.get("summary_lines") or [])
        journey.append(
            {
                "phase": "plan",
                "step": "plan_analysis_strategy",
                "status": "done",
                "detail": "先制定逐岗研究顺序，再决定每个岗位是否需要外网补证。",
                "elapsed_ms": 0,
                "summary_lines": summary_lines[:4],
            }
        )
        if research_observations:
            journey.append(
                {
                    "phase": "observe",
                    "step": "observe_research_gaps",
                    "status": "done",
                    "detail": "先观察每个岗位的历史、报录比和外网补证缺口，再判断是否补搜。",
                    "elapsed_ms": 0,
                    "summary_lines": [
                        f"观察岗位数: {len(research_observations)}",
                        f"重点岗位数: {len(list(analysis_decision.get('focus_positions') or []))}",
                    ],
                }
            )
        coverage = dict(analysis_decision.get("search_coverage") or {})
        if coverage.get("without_web_evidence", 0) > 0 or any(
            item.get("gaps") for item in list(analysis_decision.get("focus_positions") or [])
        ):
            journey.append(
                {
                    "phase": "retry",
                    "step": "retry_research",
                    "status": "done",
                    "detail": "对缺口岗位进行补证重试，优先补齐招录人数、报录比和进面分数线索。",
                    "elapsed_ms": 0,
                    "summary_lines": [
                        f"有证据岗位: {coverage.get('with_web_evidence', 0)}",
                        f"无证据岗位: {coverage.get('without_web_evidence', 0)}",
                    ],
                }
            )
        focus_positions = list(analysis_decision.get("focus_positions") or [])
        if focus_positions:
            journey.append(
                {
                    "phase": "decide",
                    "step": "decide_report_focus",
                    "status": "done",
                    "detail": "根据观察与补证结果，决定哪些岗位作为主分析对象、哪些仅保留参考。",
                    "elapsed_ms": 0,
                    "summary_lines": [
                        f"重点岗位数: {len(focus_positions)}",
                        f"焦点ID数: {len(list(analysis_decision.get('focus_position_ids') or []))}",
                    ],
                }
            )
        for item in position_researches[:5]:
            history = dict(item.get("history") or {})
            history_years = [
                str(year)
                for year in list(history.get("history_years") or [])
                if year is not None
            ]
            web_results = list(item.get("web_results") or [])
            web_search_attempts = list(item.get("web_search_attempts") or [])
            title = " / ".join(
                part
                for part in [
                    str(item.get("department_name") or "").strip(),
                    str(item.get("office_name") or "").strip(),
                    str(item.get("job_title") or "").strip(),
                ]
                if part
            ) or "未知岗位"
            journey.append(
                {
                    "phase": "research",
                    "step": f"research_{item.get('index') or len(journey)}",
                    "status": "done",
                    "detail": (
                        f"逐岗分析 {title}，"
                        f"先看历史 {history.get('record_count', 0)} 条，再做外网补证"
                    ),
                    "elapsed_ms": 0,
                    "position_label": title,
                    "history_years": history_years,
                    "latest_recruit_count": history.get("latest_recruit_count"),
                    "latest_interview_ratio": history.get("latest_interview_ratio"),
                    "web_hit_count": len(web_results),
                    "retry_count": sum(
                        1 for attempt in web_search_attempts if attempt.get("is_retry")
                    ),
                    "summary_lines": [
                        f"历史年份: {'、'.join(history_years) if history_years else '未检索到'}",
                        f"最近招录: {history.get('latest_recruit_count') or '未检索到'}",
                        f"最近报录比: {history.get('latest_interview_ratio') or '未检索到'}",
                        f"外网补证: {len(web_results)} 条",
                        f"重试次数: {sum(1 for attempt in web_search_attempts if attempt.get('is_retry'))} 次",
                    ],
                }
            )
        risk_items = list(risk_review.get("risk_items") or [])
        journey.append(
            {
                "phase": "review",
                "step": "risk_review",
                "status": "done",
                "detail": f"完成风险复核，共识别 {len(risk_items)} 项风险点。",
                "elapsed_ms": 0,
                "summary_lines": [
                    f"风险等级: {risk_review.get('risk_level') or 'unknown'}",
                    f"风险项: {len(risk_items)}",
                ],
            }
        )
        journey.append(
            {
                "phase": "conclusion",
                "step": "compose_report",
                "status": "done",
                "detail": "汇总岗位事实、历史趋势、补证结果和风险提示，形成最终报告。",
                "elapsed_ms": 0,
                "summary_lines": [
                    f"轨迹总数: {len(trace)}",
                    f"研究岗位数: {len(position_researches)}",
                ],
            }
        )
        return journey

    def _build_recommendation_context_lines(
        self,
        recommendation_context: dict[str, Any],
    ) -> list[str]:
        if not recommendation_context:
            return ["- 本次分析未接收到前置推荐 Agent 的规划上下文，直接进入岗位分析。"]

        recommendations = list(recommendation_context.get("recommendations") or [])
        summary = dict(recommendation_context.get("summary") or {})
        missing_fields = list(recommendation_context.get("missing_fields") or [])
        lines = [
            f"- 推荐 Agent 查询: {recommendation_context.get('query') or 'unknown'}",
            f"- 推荐 Agent 状态: {recommendation_context.get('status') or 'completed'}",
            f"- 推荐年份 / 类型: {recommendation_context.get('year') or 'unknown'} / {recommendation_context.get('exam_type') or 'unknown'}",
            f"- 规划候选数: {summary.get('candidate_count', len(recommendations))}",
            f"- 最终推荐数: {len(recommendations)}",
        ]
        if summary.get("filtered_count") is not None:
            lines.append(f"- 通过硬筛岗位数: {summary.get('filtered_count')}")
        if missing_fields:
            lines.append(
                "- 缺失字段: "
                + "、".join(self._map_missing_fields_to_chinese(missing_fields))
            )
        if recommendation_context.get("answer"):
            lines.append(
                "- 推荐结论: "
                + str(recommendation_context.get("answer") or "").splitlines()[0][:180]
            )
        if recommendations:
            lines.append("- Top 推荐:")
            for index, item in enumerate(recommendations[:3], start=1):
                label = self._format_position_label(item)
                score = item.get("score", 0.0)
                risk_level = item.get("risk_level") or "unknown"
                lines.append(f"  - {index}. {label} | score={score} | risk={risk_level}")
        return lines

    def _build_user_profile_lines(self, profile: dict[str, Any]) -> list[str]:
        if not profile:
            return ["- 当前未提供完整用户画像，分析主要依据岗位条件与筛选结果。"]

        def _join(values: Any) -> str:
            if isinstance(values, list):
                items = [str(item).strip() for item in values if str(item).strip()]
                return "、".join(items) if items else "无"
            text = str(values or "").strip()
            return text or "无"

        items = [
            ("专业", profile.get("major")),
            ("学历", profile.get("education")),
            ("学位", profile.get("degree")),
            ("政治面貌", profile.get("political_status")),
            ("基层年限", profile.get("grassroots_experience_years")),
            (
                "应届身份",
                "应届" if profile.get("is_fresh_graduate") else "非应届或未明确",
            ),
            ("地区偏好", profile.get("target_regions")),
            ("部门偏好", profile.get("desired_departments")),
            ("岗位偏好", profile.get("desired_positions")),
            ("排除条件", profile.get("avoid_conditions")),
            ("备注", profile.get("notes")),
        ]
        return [f"- {label}: {_join(value)}" for label, value in items]

    def _build_candidate_pool_lines(
        self,
        *,
        selected_positions: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> list[str]:
        total = int(summary.get("candidate_count") or len(selected_positions))
        exact = sum(1 for item in selected_positions if self._is_strong_match(item))
        basic = sum(1 for item in selected_positions if self._is_basic_match(item))
        risk = sum(1 for item in selected_positions if self._is_risky_match(item))
        exclude = sum(1 for item in selected_positions if not item.get("hard_filter_passed"))

        department_counter = Counter(
            str(item.get("department_name") or "未命名部门").strip() or "未命名部门"
            for item in selected_positions
        )
        education_counter = Counter(
            str(item.get("education_requirement") or "未说明").strip() or "未说明"
            for item in selected_positions
        )
        political_counter = Counter(
            str(item.get("political_status_requirement") or "未说明").strip() or "未说明"
            for item in selected_positions
        )
        major_counter = Counter(
            self._classify_major_strength(item.get("major_requirement"))
            for item in selected_positions
        )

        lines = [
            f"- 当前筛选岗位总数: {total}",
            f"- 完全匹配岗位数量: {exact}",
            f"- 基本匹配岗位数量: {basic}",
            f"- 存在风险岗位数量: {risk}",
            f"- 不建议报考岗位数量: {exclude}",
            f"- 推荐结果数: {len(recommendations)}",
            f"- 部门分布: {self._format_counter_top(department_counter)}",
            f"- 学历要求分布: {self._format_counter_top(education_counter)}",
            f"- 政治面貌要求分布: {self._format_counter_top(political_counter)}",
            f"- 专业限制强弱分布: {self._format_counter_top(major_counter)}",
        ]
        return lines

    def _build_recommendation_summary_lines(
        self,
        recommendations: list[dict[str, Any]],
    ) -> list[str]:
        if not recommendations:
            return ["- 当前没有生成可推荐岗位，请先检查筛选条件或补充用户画像。"]

        buckets = {
            "优先报考岗位": [],
            "冲刺岗位": [],
            "稳妥备选岗位": [],
            "谨慎报考岗位": [],
            "不建议报考岗位": [],
        }
        for item in recommendations[:10]:
            recommend_level = str(item.get("recommend_level") or "").lower()
            risk_level = str(item.get("risk_level") or "").lower()
            label = self._format_position_label(item)
            if recommend_level in {"strong_match", "good_match"} and risk_level in {"low", "medium"}:
                buckets["优先报考岗位"].append(label)
            elif recommend_level == "medium_match" or risk_level == "medium":
                buckets["冲刺岗位"].append(label)
            elif recommend_level == "weak_match" and risk_level in {"low", "medium"}:
                buckets["稳妥备选岗位"].append(label)
            elif risk_level == "high" or bool(item.get("need_manual_confirm")):
                buckets["谨慎报考岗位"].append(label)
            else:
                buckets["不建议报考岗位"].append(label)

        lines: list[str] = []
        for title, values in buckets.items():
            if values:
                lines.append(f"- {title}: {('、'.join(values[:4]))}")
        if not lines:
            lines.append("- 当前推荐结果不足以形成明确分组，建议先补充画像或缩小筛选范围。")
        return lines

    def _build_history_trend_lines(self, position_researches: list[dict[str, Any]]) -> list[str]:
        if not position_researches:
            return ["- 暂无历史招录记录，无法对 2024-2026 年趋势做可靠判断。"]

        lines: list[str] = []
        for item in position_researches[:5]:
            title = self._format_position_label(item)
            history = dict(item.get("history") or {})
            years = [str(year) for year in list(history.get("history_years") or []) if year is not None]
            lines.append(
                f"- {title}: 历年 {('、'.join(years) if years else '未检索到')}"
                f"，招录 {history.get('latest_recruit_count', '未检索到')}"
                f"，趋势 {history.get('recruit_count_trend', 'unknown')}"
            )
        return lines

    def _build_competition_lines(self, position_researches: list[dict[str, Any]]) -> list[str]:
        if not position_researches:
            return ["- 暂无竞争比数据。"]

        lines: list[str] = [
            "- 计算说明：当前分析优先使用岗位历史表中的面试/报录比字段作为历史竞争强度参考；2026 年最终报名数据未公布时，仅展示“当前竞争热度”或“历史竞争比”。",
        ]
        for item in position_researches[:5]:
            title = self._format_position_label(item)
            history = dict(item.get("history") or {})
            ratio = history.get("latest_interview_ratio")
            trend = history.get("interview_ratio_trend", "unknown")
            if ratio is None:
                ratio_text = "无法确认"
            else:
                ratio_text = f"{ratio:.2f}:1"
            lines.append(f"- {title}: 历史竞争比 {ratio_text}，趋势 {trend}")
        return lines

    def _build_score_lines(self, position_researches: list[dict[str, Any]]) -> list[str]:
        if not position_researches:
            return ["- 暂无进面分数数据，不能编造预测值。"]
        lines = [
            "- 当前岗位表里未直接包含统一的历史进面分字段；如果外网检索到了官方分数，会在单岗分析卡片中补充。没有检索到时，统一标注为“无法确认”。",
        ]
        for item in position_researches[:5]:
            title = self._format_position_label(item)
            lines.append(f"- {title}: 历史进面分无法确认，2026 预测进面分区间无法确认。")
        return lines

    def _build_comparison_table_lines(
        self,
        recommendations: list[dict[str, Any]],
    ) -> list[str]:
        if not recommendations:
            return ["- 当前没有足够的推荐岗位可生成横向对比表。"]

        lines = [
            "| 推荐排序 | 部门 | 职位名称 | 招录人数 | 匹配度 | 历史最低进面分 | 竞争热度 | 风险等级 | 推荐建议 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for index, item in enumerate(recommendations[:10], start=1):
            title = self._format_position_label(item)
            lines.append(
                "| "
                f"{index} | "
                f"{self._table_value(item.get('department_name'))} | "
                f"{self._table_value(title)} | "
                f"{self._table_value(item.get('recruit_count') or '未填写')} | "
                f"{self._table_value(item.get('score', '0'))} | "
                f"{self._table_value('无法确认')} | "
                f"{self._table_value(item.get('risk_level') or 'unknown')} | "
                f"{self._table_value(item.get('risk_level') or 'unknown')} | "
                f"{self._table_value(self._recommendation_conclusion(str(item.get('recommend_level') or ''), str(item.get('risk_level') or ''), item))} |"
            )
        return lines

    def _build_registration_notes_lines(
        self,
        *,
        selected_positions: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> list[str]:
        if not selected_positions:
            return ["- 当前没有可核对的岗位。"]

        lines = [
            "- 专业名称是否完全一致：优先以岗位表与专业目录的原文为准。",
            "- 学历学位是否符合：学历和学位都要逐项核对。",
            "- 政治面貌要求：党员、预备党员、团员、群众等必须逐项核对。",
            "- 基层工作经历要求：有年限要求的岗位要核算到报考截止日。",
            "- 服务基层项目要求：有相关备注时必须核对原文。",
            "- 备注栏限制：如“仅限”“须提供”“电话确认”“以官方为准”等，必须人工复核。",
            "- 资格证书要求：证书、资格、执业资格等都属于硬性条件。",
            "- 是否需要电话确认招录单位：凡是备注不清晰或存在歧义的，建议先电话确认。",
        ]
        if risk_review.get("risk_items"):
            lines.append("- 风险项已识别，建议优先逐条复核风险项，再决定是否报考。")
        return lines

    def _build_final_advice_lines(
        self,
        *,
        recommendations: list[dict[str, Any]],
        selected_positions: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> list[str]:
        if not recommendations:
            return [
                "- 当前没有足够清晰的推荐岗位，建议先缩小筛选范围，或补充专业、学历、学位和地区偏好。",
            ]

        strong = [
            self._format_position_label(item)
            for item in recommendations
            if str(item.get("recommend_level") or "").lower() in {"strong_match", "good_match"}
            and str(item.get("risk_level") or "").lower() in {"low", "medium"}
        ][:3]
        backup = [
            self._format_position_label(item)
            for item in recommendations
            if str(item.get("recommend_level") or "").lower() == "weak_match"
            and str(item.get("risk_level") or "").lower() in {"low", "medium"}
        ][:3]
        caution = [
            self._format_position_label(item)
            for item in recommendations
            if str(item.get("risk_level") or "").lower() == "high"
            or bool(item.get("need_manual_confirm"))
        ][:3]
        excluded = [
            self._format_position_label(item)
            for item in selected_positions
            if not item.get("hard_filter_passed")
        ][:3]

        lines = [
            f"- 最推荐报考哪几个岗位: {('、'.join(str(item) for item in strong) if strong else '暂无明确强推荐')}",
            f"- 哪些岗位适合冲刺: {('、'.join(str(item) for item in backup) if backup else '暂无明确冲刺项')}",
            f"- 哪些岗位作为备选: {('、'.join(str(item) for item in backup) if backup else '暂无明确备选项')}",
            f"- 哪些岗位应该排除: {('、'.join(str(item) for item in excluded) if excluded else '暂无明显排除项')}",
            f"- 当前风险等级: {str(risk_review.get('risk_level') or 'unknown')}",
            "- 下一步应该做什么: 先核对硬性条件，再对高风险岗位逐条复核备注与官方公告。",
        ]
        if caution:
            lines.append(f"- 需要谨慎的岗位: {('、'.join(caution))}")
        return lines

    def _is_strong_match(self, item: dict[str, Any]) -> bool:
        recommend_level = str(item.get("recommend_level") or "").lower()
        risk_level = str(item.get("risk_level") or "").lower()
        return recommend_level in {"strong_match", "good_match"} and risk_level in {"low", "medium"}

    def _is_basic_match(self, item: dict[str, Any]) -> bool:
        if not item.get("hard_filter_passed"):
            return False
        recommend_level = str(item.get("recommend_level") or "").lower()
        score = float(item.get("score") or 0)
        return recommend_level == "weak_match" or score >= 60

    def _is_risky_match(self, item: dict[str, Any]) -> bool:
        risk_level = str(item.get("risk_level") or "").lower()
        return risk_level == "high" or bool(item.get("need_manual_confirm"))

    def _classify_major_strength(self, requirement: Any) -> str:
        text = str(requirement or "").strip()
        if not text or any(token in text for token in ("不限", "不限制", "无专业限制")):
            return "不限"
        if any(token in text for token in ("类", "相关", "大类", "一级学科")):
            return "中等限制"
        return "强限制"

    def _format_counter_top(self, counter: Counter[str]) -> str:
        if not counter:
            return "暂无"
        items = [f"{key}{value}项" for key, value in counter.most_common(4)]
        return "，".join(items)

    def _format_position_label(self, item: dict[str, Any]) -> str:
        department = str(item.get("department_name") or "").strip()
        office = str(item.get("office_name") or "").strip()
        job_title = str(item.get("job_title") or "").strip()
        return " / ".join(part for part in [department, office, job_title] if part) or "未知岗位"

    def _format_text_items(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            text = str(value).strip()
            return [text] if text else []

        items: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = (
                    item.get("text")
                    or item.get("explanation")
                    or item.get("reason")
                    or item.get("content")
                    or item.get("detail")
                )
                label = str(item.get("type") or item.get("risk_type") or "").strip()
                text_value = str(text or "").strip()
                if label and text_value:
                    items.append(f"{label}: {text_value}")
                elif text_value:
                    items.append(text_value)
            else:
                text = str(item).strip()
                if text:
                    items.append(text)
        return items

    def _format_position_info(self, item: dict[str, Any]) -> str:
        fields = [
            ("招录人数", item.get("recruit_count")),
            ("专业要求", item.get("major_requirement")),
            ("学历要求", item.get("education_requirement")),
            ("学位要求", item.get("degree_requirement")),
            ("政治面貌", item.get("political_status_requirement")),
            (
                "工作地点",
                item.get("work_location")
                or item.get("position_distribution")
                or item.get("household_registration_location"),
            ),
            ("备注", item.get("remarks")),
        ]
        parts = []
        for label, value in fields:
            text = self._table_value(value)
            if text != "无法确认":
                parts.append(f"{label}: {text}")
        return "；".join(parts) if parts else "无法确认"

    def _table_value(self, value: Any) -> str:
        text = str(value or "").replace("|", " ").strip()
        return text or "无法确认"

    def _recommendation_conclusion(
        self,
        recommend_level: str,
        risk_level: str,
        item: dict[str, Any],
    ) -> str:
        normalized_level = recommend_level.lower().strip()
        normalized_risk = risk_level.lower().strip()
        if normalized_risk == "high" or bool(item.get("need_manual_confirm")):
            return "谨慎报考"
        if normalized_level == "strong_match":
            return "最推荐报考"
        if normalized_level == "good_match":
            return "适合冲刺"
        if normalized_level == "weak_match":
            return "可作备选"
        return "建议排除"

    def _build_user_profile_lines(self, profile: dict[str, Any]) -> list[str]:
        if not profile:
            return ["- 当前未加载到完整用户画像，分析主要依据岗位条件与筛选结果。"]

        fields = [
            ("专业", profile.get("major")),
            ("学历", profile.get("education")),
            ("学位", profile.get("degree")),
            ("政治面貌", profile.get("political_status")),
            ("基层年限", profile.get("grassroots_experience_years")),
            ("应届身份", "是" if profile.get("is_fresh_graduate") else "否"),
            ("资格证书/备注", profile.get("notes")),
            ("地区偏好", "、".join(list(profile.get("target_regions") or []))),
            ("部门偏好", "、".join(list(profile.get("desired_departments") or []))),
            ("岗位偏好", "、".join(list(profile.get("desired_positions") or []))),
        ]
        lines = []
        for label, value in fields:
            if value in (None, "", [], {}):
                value = "未提供"
            lines.append(f"- {label}: {value}")
        return lines

    def _build_candidate_pool_lines(
        self,
        *,
        selected_positions: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> list[str]:
        if not selected_positions:
            return ["- 当前筛选岗位总数为 0，无法继续生成候选池分析。"]

        exact_match_count = sum(
            1
            for item in selected_positions
            if bool(item.get("hard_filter_passed"))
            and str(item.get("risk_level") or "").lower() != "high"
            and str(item.get("recommend_level") or "").lower() in {"strong_match", "good_match"}
        )
        basic_match_count = sum(
            1
            for item in selected_positions
            if bool(item.get("hard_filter_passed"))
            and item not in recommendations
            and str(item.get("risk_level") or "").lower() != "high"
        )
        risk_count = sum(
            1
            for item in selected_positions
            if str(item.get("risk_level") or "").lower() in {"medium", "high"}
            or bool(item.get("need_manual_confirm"))
        )
        not_recommended_count = max(
            0,
            len(selected_positions) - exact_match_count - basic_match_count,
        )
        department_distribution = _counter_lines(
            selected_positions,
            "department_name",
            "部门分布",
        )
        education_distribution = _counter_lines(
            selected_positions,
            "education_requirement",
            "学历要求分布",
        )
        political_distribution = _counter_lines(
            selected_positions,
            "political_status_requirement",
            "政治面貌要求分布",
        )
        major_strength = Counter(
            _classify_major_requirement(item.get("major_requirement"))
            for item in selected_positions
        )

        lines = [
            f"- 当前筛选岗位总数: {len(selected_positions)}",
            f"- 完全匹配岗位数量: {exact_match_count}",
            f"- 基本匹配岗位数量: {basic_match_count}",
            f"- 存在风险岗位数量: {risk_count}",
            f"- 不建议报考岗位数量: {not_recommended_count}",
        ]
        if summary:
            lines.append(
                f"- 候选池摘要: 已筛选 {summary.get('candidate_count', len(selected_positions))} 条，"
                f"入选 {summary.get('recommendation_count', len(recommendations))} 条"
            )
        lines.extend(department_distribution)
        lines.extend(education_distribution)
        lines.extend(political_distribution)
        lines.append(
            "- 专业限制强弱分布: "
            + "、".join(
                f"{label} {count} 条"
                for label, count in major_strength.items()
                if count
            )
        )
        return lines

    def _build_recommendation_summary_lines(
        self,
        recommendations: list[dict[str, Any]],
    ) -> list[str]:
        if not recommendations:
            return ["- 当前没有足够清晰的优先报考岗位，建议先补充筛选条件。"]

        buckets = {
            "优先报考岗位": [],
            "冲刺岗位": [],
            "稳妥备选岗位": [],
            "谨慎报考岗位": [],
            "不建议报考岗位": [],
        }
        for item in recommendations[:10]:
            level = str(item.get("recommend_level") or "").lower()
            risk_level = str(item.get("risk_level") or "").lower()
            label = self._format_position_label(item)
            if level == "strong_match" and risk_level != "high":
                buckets["优先报考岗位"].append(label)
            elif level == "good_match" and risk_level in {"low", "medium"}:
                buckets["冲刺岗位"].append(label)
            elif level == "weak_match" and risk_level in {"low", "medium"}:
                buckets["稳妥备选岗位"].append(label)
            elif risk_level == "high" or bool(item.get("need_manual_confirm")):
                buckets["谨慎报考岗位"].append(label)
            else:
                buckets["不建议报考岗位"].append(label)

        lines = []
        for bucket_name, items in buckets.items():
            if items:
                lines.append(f"- {bucket_name}: {'；'.join(items[:3])}")
        return lines or ["- 暂无可明确归类的推荐岗位。"]

    def _build_history_trend_lines(
        self,
        position_researches: list[dict[str, Any]],
    ) -> list[str]:
        if not position_researches:
            return ["- 暂无历史招录数据可对比。"]
        lines = []
        for item in position_researches[:8]:
            title = self._format_position_label(item)
            history = dict(item.get("history") or {})
            history_years = ", ".join(
                str(year) for year in list(history.get("history_years") or [])[:5]
            ) or "未检索到"
            lines.append(
                f"- {title}: {history_years}；"
                f"招录趋势 {history.get('recruit_count_trend', 'unknown')}；"
                f"条件门槛变化 {history.get('interview_ratio_trend', 'unknown')}"
            )
        return lines

    def _build_competition_lines(
        self,
        position_researches: list[dict[str, Any]],
    ) -> list[str]:
        if not position_researches:
            return ["- 暂无报录比数据。"]
        lines = []
        for item in position_researches[:8]:
            title = self._format_position_label(item)
            history = dict(item.get("history") or {})
            latest_ratio = history.get("latest_interview_ratio")
            if latest_ratio is None:
                ratio_text = "无法确认"
            else:
                ratio_text = f"约 {latest_ratio:.2f}:1"
            lines.append(
                f"- {title}: 历史/当前竞争比 {ratio_text}，"
                f"竞争趋势 {history.get('interview_ratio_trend', 'unknown')}。"
            )
        return lines

    def _build_score_lines(
        self,
        position_researches: list[dict[str, Any]],
    ) -> list[str]:
        if not position_researches:
            return ["- 暂无进面分数数据。"]
        lines = [
            "- 目前岗位表字段中未包含可核验的最终进面分，若外部检索未返回可靠来源，则必须标注“无法确认”。",
        ]
        for item in position_researches[:8]:
            title = self._format_position_label(item)
            history_records = list(item.get("history_records") or [])
            score_note = "无法确认"
            if history_records:
                score_note = "、".join(
                    f"{record.get('year') or '未知'}年：{record.get('remarks') or '未公开'}"
                    for record in history_records[:3]
                )
            lines.append(f"- {title}: {score_note}")
        return lines

    def _build_position_analysis_block(
        self,
        rank: int,
        item: dict[str, Any],
    ) -> list[str]:
        title = self._format_position_label(item)
        score = item.get("score", 0)
        recommend_level = str(item.get("recommend_level") or "weak_match")
        risk_level = str(item.get("risk_level") or "unknown")
        history = dict(item.get("history") or {})
        history_records = list(item.get("history_records") or [])
        web_results = list(item.get("web_results") or [])
        web_search_attempts = list(item.get("web_search_attempts") or [])
        analysis_text = str(item.get("analysis_text") or "").strip()
        reasons = self._format_text_items(item.get("reasons"))
        risks = self._format_text_items(item.get("risks"))
        lines = [
            f"### {rank}. {title}",
            f"- 岗位信息: {self._format_position_info(item)}",
            f"- 匹配度: {score}",
            f"- 推荐等级: {recommend_level}",
            f"- 风险等级: {risk_level}",
            f"- 历史招录人数: {history.get('latest_recruit_count') or '无法确认'}",
            f"- 历史报录比: {history.get('latest_interview_ratio') or '无法确认'}",
            "- 历史进面分: 无法确认",
            "- 2026 预测进面分: 无法确认",
        ]
        if history.get("history_years"):
            lines.append(
                "- 历史年份: "
                + "、".join(str(year) for year in list(history.get("history_years") or [])[:5])
            )
        if history_records:
            lines.append("- 逐年记录:")
            for record in history_records[:3]:
                lines.append(
                    "  - "
                    f"{record.get('year') or '未知年份'}年 | "
                    f"招录 {record.get('recruit_count') or '未知'} | "
                    f"报录比 {record.get('interview_ratio') or '未知'} | "
                    f"备注 {str(record.get('remarks') or '无').strip()[:60]}"
                )
        if reasons:
            lines.append(f"- 风险/匹配依据: {'；'.join(reasons[:4])}")
        if risks:
            lines.append(f"- 风险点: {'；'.join(risks[:4])}")
        if web_results:
            lines.append(f"- 外网补证: 已检索到 {len(web_results)} 条线索")
            top_sources = [
                str(result.get("title") or result.get("doc_title") or result.get("source") or "").strip()
                for result in web_results[:3]
                if str(result.get("title") or result.get("doc_title") or result.get("source") or "").strip()
            ]
            if top_sources:
                lines.append(f"- 外网来源: {'；'.join(top_sources)}")
        else:
            lines.append("- 外网补证: 未检索到有效网页正文，需要以官方公告再核验。")
        if web_search_attempts:
            retry_count = sum(1 for attempt in web_search_attempts if attempt.get("is_retry"))
            lines.append(
                f"- 外网检索尝试: {len(web_search_attempts)} 次，重试 {retry_count} 次"
            )
        if analysis_text:
            first_lines = [
                line.strip()
                for line in analysis_text.splitlines()
                if line.strip()
            ][:3]
            if first_lines:
                lines.append("- 研究摘要:")
                for line in first_lines:
                    lines.append(f"  - {line[:140]}")
        lines.append(f"- 推荐建议: {self._recommendation_conclusion(recommend_level, risk_level, item)}")
        lines.append(f"- 注意事项: {self._registration_caution(item, history)}")
        lines.append("")
        return lines

    def _build_comparison_table_lines(
        self,
        positions: list[dict[str, Any]],
    ) -> list[str]:
        if not positions:
            return ["- 暂无岗位可用于横向对比。"]

        header = (
            "| 推荐排序 | 部门 | 职位名称 | 招录人数 | 匹配度 | 历史最低进面分 | 竞争热度 | 风险等级 | 推荐建议 |"
        )
        separator = (
            "|---|---|---|---:|---:|---|---|---|---|"
        )
        rows = [header, separator]
        for index, item in enumerate(positions[:10], start=1):
            title = self._format_position_label(item)
            history = dict(item.get("history") or {})
            risk_level = str(item.get("risk_level") or "unknown")
            rows.append(
                "| "
                f"{index} | "
                f"{item.get('department_name') or '未知部门'} | "
                f"{title} | "
                f"{item.get('recruit_count') or '未知'} | "
                f"{item.get('score', 0)} | "
                f"{history.get('latest_interview_ratio') or '无法确认'} | "
                f"{history.get('interview_ratio_trend', 'unknown')} | "
                f"{risk_level} | "
                f"{self._recommendation_conclusion(str(item.get('recommend_level') or ''), risk_level, item)} |"
            )
        return rows

    def _build_registration_notes_lines(
        self,
        *,
        selected_positions: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> list[str]:
        note_items = []
        for item in selected_positions[:10]:
            note_text = str(item.get("remarks") or "").strip()
            if note_text:
                note_items.append(note_text)
        risk_items = list(risk_review.get("risk_items") or [])
        lines = [
            "- 专业名称是否完全一致，若仅是“大类相关”要单独确认。",
            "- 学历学位是否同时满足，不能只看其中一项。",
            "- 政治面貌、基层经历、服务基层项目要求必须逐项核对。",
            "- 备注栏里的“以官方为准、电话确认、资格审查”等字样，必须当作硬提醒。",
            "- 若岗位信息中有证书、资格、体测、专业测试等描述，要优先复核原文。",
            "- 需要电话确认时，建议把单位名称、岗位代码和关键限制条件提前整理好。",
        ]
        if note_items:
            lines.append("- 备注栏限制:")
            for note in note_items[:5]:
                lines.append(f"  - {note[:120]}")
        if risk_items:
            lines.append("- 风险项提醒:")
            for item in risk_items[:5]:
                lines.append(
                    f"  - {item.get('risk_type')}: {item.get('suggestion') or item.get('explanation') or '需要人工复核'}"
                )
        return lines

    def _build_final_advice_lines(
        self,
        *,
        recommendations: list[dict[str, Any]],
        selected_positions: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> list[str]:
        if not recommendations:
            return ["- 当前没有足够明确的推荐岗位，建议先补充用户画像或扩大候选池。"]

        grouped: dict[str, list[str]] = {
            "最推荐报考": [],
            "适合冲刺": [],
            "适合作为备选": [],
            "建议谨慎": [],
            "建议排除": [],
        }
        for item in recommendations[:10]:
            level = str(item.get("recommend_level") or "").lower()
            risk_level = str(item.get("risk_level") or "").lower()
            label = self._format_position_label(item)
            if level == "strong_match" and risk_level in {"low", "medium"}:
                grouped["最推荐报考"].append(label)
            elif level == "good_match" and risk_level in {"low", "medium"}:
                grouped["适合冲刺"].append(label)
            elif level == "weak_match" and risk_level in {"low", "medium"}:
                grouped["适合作为备选"].append(label)
            elif risk_level == "high" or bool(item.get("need_manual_confirm")):
                grouped["建议谨慎"].append(label)
            else:
                grouped["建议排除"].append(label)

        lines = []
        for bucket, items in grouped.items():
            if items:
                lines.append(f"- {bucket}: {'；'.join(items[:4])}")
        lines.append("- 接下来应该做什么: 优先核对最推荐岗位的资格条件，再对冲刺岗位做电话或公告原文复核，最后再决定投递顺序。")
        if risk_review.get("risk_items"):
            lines.append(
                f"- 风险提示: 当前识别到 {len(risk_review.get('risk_items') or [])} 项风险点，投递前务必逐项排查。"
            )
        if selected_positions and len(selected_positions) > 10:
            lines.append("- 候选池较大，建议再按地区或部门继续缩小范围。")
        return lines

    def _registration_caution(
        self,
        item: dict[str, Any],
        history: dict[str, Any],
    ) -> str:
        remarks = str(item.get("remarks") or "").strip()
        caution_parts = [
            "专业、学历、学位和政治面貌先做硬核对",
            "历史招录和报录比只能作为参考，不要替代公告原文",
        ]
        if remarks:
            caution_parts.append(f"备注中存在“{remarks[:20]}...”等额外限制，需人工复核")
        if history.get("latest_interview_ratio") is None:
            caution_parts.append("报录比字段缺失，需外网补证或人工查原文")
        return "；".join(caution_parts)

    def _build_history_trend_lines_v2(
        self,
        position_researches: list[dict[str, Any]],
    ) -> list[str]:
        if not position_researches:
            return ["- 暂无历史招录记录，无法对 2024-2026 趋势做可靠判断。"]

        lines: list[str] = []
        for item in position_researches[:5]:
            title = self._format_position_label(item)
            history = dict(item.get("history") or {})
            years = [
                str(year)
                for year in list(history.get("history_years") or [])
                if year is not None
            ]
            recruit_trend = str(history.get("recruit_count_trend") or "unknown")
            ratio_trend = str(history.get("interview_ratio_trend") or "unknown")
            latest_recruit = history.get("latest_recruit_count")
            latest_ratio = history.get("latest_interview_ratio")
            lines.append(
                f"- {title}: 历史年份 {('、'.join(years) if years else '缺失')}，"
                f"最近招录 {latest_recruit if latest_recruit is not None else '缺失'}，"
                f"招录趋势 {recruit_trend}，报录比趋势 {ratio_trend}"
            )
            if latest_ratio is not None:
                lines.append(f"  - 最新报录比 {float(latest_ratio):.2f}:1")
            else:
                lines.append("  - 最新报录比缺失，需要继续补证。")
        return lines

    def _build_competition_lines_v2(
        self,
        position_researches: list[dict[str, Any]],
    ) -> list[str]:
        if not position_researches:
            return ["- 暂无报录比/竞争比数据。"]

        lines: list[str] = [
            "- 说明：2026 年若没有最终报名结果，这里展示的是历史报录比与当前竞争热度，不写成最终竞争比。",
        ]
        for item in position_researches[:5]:
            title = self._format_position_label(item)
            history = dict(item.get("history") or {})
            ratio = history.get("latest_interview_ratio")
            trend = str(history.get("interview_ratio_trend") or "unknown")
            if ratio is None:
                ratio_text = "缺失"
            else:
                ratio_text = f"{float(ratio):.2f}:1"
            lines.append(
                f"- {title}: 当前/历史报录比 {ratio_text}，竞争趋势 {trend}，"
                f"历史记录数 {history.get('record_count', 0)}"
            )
        return lines

    def _build_score_lines_v2(
        self,
        position_researches: list[dict[str, Any]],
    ) -> list[str]:
        if not position_researches:
            return ["- 暂无可核验的进面分数数据。"]

        lines: list[str] = [
            "- 说明：如果无法从公开来源拿到官方最低进面分，则必须明确写“缺失”，不能编造。",
        ]
        for item in position_researches[:5]:
            title = self._format_position_label(item)
            history_records = list(item.get("history_records") or [])
            if history_records:
                record_bits = []
                for record in history_records[:3]:
                    record_bits.append(
                        f"{record.get('year') or '未知'}年："
                        f"{record.get('remarks') or record.get('interview_ratio') or '无公开分数'}"
                    )
                score_note = "；".join(record_bits)
            else:
                score_note = "缺失"
            lines.append(f"- {title}: {score_note}")
        return lines

    def _build_position_analysis_block_v2(
        self,
        rank: int,
        item: dict[str, Any],
    ) -> list[str]:
        title = self._format_position_label(item)
        score = item.get("score", 0)
        recommend_level = str(item.get("recommend_level") or "weak_match")
        risk_level = str(item.get("risk_level") or "unknown")
        history = dict(item.get("history") or {})
        history_records = list(item.get("history_records") or [])
        web_results = list(item.get("web_results") or [])
        web_search_attempts = list(item.get("web_search_attempts") or [])
        analysis_text = str(item.get("analysis_text") or "").strip()
        reasons = self._format_text_items(item.get("reasons"))
        risks = self._format_text_items(item.get("risks"))
        lines = [
            f"### {rank}. {title}",
            f"- 岗位信息: {self._format_position_info(item)}",
            f"- 匹配度: {score}",
            f"- 推荐等级: {recommend_level}",
            f"- 风险等级: {risk_level}",
            f"- 历史招录人数: {history.get('latest_recruit_count') if history.get('latest_recruit_count') is not None else '缺失'}",
            f"- 历史报录比: {history.get('latest_interview_ratio') if history.get('latest_interview_ratio') is not None else '缺失'}",
            "- 2026 预测进面分: 缺少官方分数时仅能给出风险判断，不能硬编具体分数。",
        ]
        if history.get("history_years"):
            lines.append(
                "- 2024-2026 历年年份: "
                + "、".join(str(year) for year in list(history.get("history_years") or [])[:5])
            )
        if history_records:
            lines.append("#### 历年逐项数据")
            for record in history_records[:3]:
                lines.append(
                    f"- {record.get('year') or '未知'}年："
                    f"招录 {record.get('recruit_count') or '缺失'}，"
                    f"报录比 {record.get('interview_ratio') or '缺失'}，"
                    f"备注 {str(record.get('remarks') or '无').strip()[:80]}"
                )
        if reasons:
            lines.append("#### 推荐依据")
            for reason in reasons[:4]:
                lines.append(f"- {reason}")
        if risks:
            lines.append("#### 风险点")
            for risk in risks[:4]:
                lines.append(f"- {risk}")
        if web_results:
            lines.append(f"- 外网证据: 已检索到 {len(web_results)} 条线索")
            lines.append("#### 外网补证详情")
            for index, result in enumerate(web_results[:5], 1):
                result_title = str(
                    result.get("title")
                    or result.get("doc_title")
                    or result.get("source")
                    or "未命名线索"
                ).strip()
                result_source = str(result.get("source") or result.get("retrieved_via") or "").strip()
                result_url = str(
                    result.get("url")
                    or result.get("final_url")
                    or result.get("link")
                    or ""
                ).strip()
                result_snippet = str(
                    result.get("snippet")
                    or result.get("content")
                    or result.get("summary")
                    or ""
                ).strip()
                lines.append(f"- 线索 {index}: {result_title}")
                if result_source:
                    lines.append(f"  - 来源: {result_source}")
                if result_url:
                    lines.append(f"  - 链接: {result_url}")
                if result_snippet:
                    lines.append(f"  - 摘要: {result_snippet[:180]}")
            if len(web_results) > 5:
                lines.append(f"- 其余 {len(web_results) - 5} 条外网证据已参与分析，但此处不再全部展开。")
            top_sources = [
                str(result.get("title") or result.get("doc_title") or result.get("source") or "").strip()
                for result in web_results[:3]
                if str(result.get("title") or result.get("doc_title") or result.get("source") or "").strip()
            ]
            if top_sources:
                lines.append(f"- 外网来源: {'、'.join(top_sources)}")
        else:
            lines.append("- 外网证据: 未检索到可靠网页正文，需要继续用官方公告或原始 PDF 核验。")
        if web_search_attempts:
            retry_count = sum(1 for attempt in web_search_attempts if attempt.get("is_retry"))
            lines.append(f"- 外网检索尝试: {len(web_search_attempts)} 次，重试 {retry_count} 次")
            lines.append("#### 外网检索过程")
            for index, attempt in enumerate(web_search_attempts[:5], 1):
                query_text = str(attempt.get("query") or "未记录查询词").strip()
                hit_count = attempt.get("hit_count")
                fetched_count = attempt.get("fetched_count")
                browser_fallback_count = attempt.get("browser_fallback_count")
                attempt_index = attempt.get("attempt_index")
                lines.append(
                    f"- 尝试 {index}"
                    f"{f'（第 {attempt_index} 次）' if attempt_index else ''}: {query_text}"
                )
                lines.append(
                    "  - "
                    f"命中 {hit_count if hit_count is not None else '缺失'} 条，"
                    f"抓取 {fetched_count if fetched_count is not None else '缺失'} 条，"
                    f"浏览器补抓 {browser_fallback_count if browser_fallback_count is not None else '缺失'} 条"
                )
        if analysis_text:
            first_lines = [
                line.strip()
                for line in analysis_text.splitlines()
                if line.strip()
            ][:3]
            if first_lines:
                lines.append("#### 分析摘要")
                for line in first_lines:
                    lines.append(f"- {line[:140]}")
        lines.append(f"- 结论: {self._recommendation_conclusion(recommend_level, risk_level, item)}")
        lines.append(f"- 核验事项: {self._registration_caution(item, history)}")
        lines.append("")
        return lines

    def _build_comparison_table_lines_v2(
        self,
        recommendations: list[dict[str, Any]],
    ) -> list[str]:
        if not recommendations:
            return ["- 暂无足够岗位可生成横向对比表。"]

        lines = [
            "| 推荐排序 | 部门 | 职位名称 | 招录人数 | 匹配度 | 历史最低进面分 | 竞争热度 | 风险等级 | 推荐建议 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for index, item in enumerate(recommendations[:10], start=1):
            history = dict(item.get("history") or {})
            lowest_score = history.get("latest_score")
            if lowest_score in (None, ""):
                lowest_score = item.get("latest_score")
            if lowest_score in (None, ""):
                lowest_score = "缺失"
            heat = item.get("competition_heat")
            if heat in (None, ""):
                heat = history.get("interview_ratio_trend") or "unknown"
            lines.append(
                "| "
                f"{index} | "
                f"{self._table_value(item.get('department_name'))} | "
                f"{self._table_value(self._format_position_label(item))} | "
                f"{self._table_value(item.get('recruit_count') or '缺失')} | "
                f"{self._table_value(item.get('score', '0'))} | "
                f"{self._table_value(lowest_score)} | "
                f"{self._table_value(heat)} | "
                f"{self._table_value(item.get('risk_level') or 'unknown')} | "
                f"{self._table_value(self._recommendation_conclusion(str(item.get('recommend_level') or ''), str(item.get('risk_level') or ''), item))} |"
            )
        return lines

    def _build_registration_notes_lines_v2(
        self,
        *,
        selected_positions: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> list[str]:
        if not selected_positions:
            return ["- 暂无可核验的岗位。"]

        lines = [
            "- 专业名称是否完全一致，若备注写明“按专业目录解释”要单独核验。",
            "- 学历、学位要同时满足，不能只满足其中一个。",
            "- 政治面貌、基层经历、服务基层项目、资格证书都要逐条检查。",
            "- 备注中如果出现“电话确认”“以公告为准”“请提前咨询”等字样，要先核验原文。",
        ]
        for item in selected_positions[:5]:
            note_text = str(item.get("remarks") or "").strip()
            if note_text:
                lines.append(f"- {self._format_position_label(item)} 备注：{note_text[:120]}")
        risk_items = list(risk_review.get("risk_items") or [])
        if risk_items:
            lines.append("- 风险提醒：")
            for risk in risk_items[:5]:
                lines.append(
                    f"  - {risk.get('risk_type')}: {risk.get('suggestion') or risk.get('explanation') or '需要人工复核'}"
                )
        return lines

    def _build_final_advice_lines_v2(
        self,
        *,
        recommendations: list[dict[str, Any]],
        selected_positions: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> list[str]:
        if not recommendations:
            return ["- 暂无足够数据形成最终报考建议。"]

        strong = [
            self._format_position_label(item)
            for item in recommendations
            if str(item.get("recommend_level") or "").lower() in {"strong_match", "good_match"}
            and str(item.get("risk_level") or "").lower() in {"low", "medium"}
        ][:4]
        cautious = [
            self._format_position_label(item)
            for item in recommendations
            if str(item.get("risk_level") or "").lower() == "high" or bool(item.get("need_manual_confirm"))
        ][:4]
        backup = [
            self._format_position_label(item)
            for item in recommendations
            if str(item.get("recommend_level") or "").lower() == "weak_match"
        ][:4]

        lines = [
            f"- 最推荐报考：{('、'.join(str(item) for item in strong) if strong else '暂无明确首选')}",
            f"- 冲刺岗位：{('、'.join(str(item) for item in backup[:2]) if backup else '暂无')}",
            f"- 谨慎报考：{('、'.join(str(item) for item in cautious) if cautious else '暂无')}",
            "- 接下来先核对硬条件，再决定是否缩小范围或补充证据。",
        ]
        if len(selected_positions) > 10:
            lines.append("- 当前候选池较大，建议继续按地区/部门/竞争热度分层筛选。")
        if risk_review.get("risk_items"):
            lines.append(
                f"- 已识别 {len(risk_review.get('risk_items') or [])} 个风险点，建议先处理高风险条目。"
            )
        return lines

    def _build_fallback_report(
        self,
        scope: dict[str, Any],
        position_facts: dict[str, Any],
        risk_review: dict[str, Any],
    ) -> str:
        report_title = str(scope.get("report_title") or "岗位分析报告")
        recommendation_count = len(position_facts.get("recommendations") or [])
        risk_level = str(risk_review.get("risk_level") or "unknown")
        return (
            f"# {report_title}\n\n"
            "## 概览\n"
            f"- 推荐岗位数: {recommendation_count}\n"
            f"- 风险等级: {risk_level}"
        )

    def _build_web_retry_query(self, query: str) -> str | None:
        normalized = str(query or "").strip()
        if not normalized or "瀹樻柟鍏憡" in normalized:
            return None
        tokens = [token for token in re.split(r"\s+", normalized) if token]
        core = " ".join(tokens[:4]).strip() or normalized
        if any(keyword in normalized for keyword in ("进面分", "面试名单", "面试分")):
            return f"{core} 官方公告 面试名单 进面分"
        if any(keyword in normalized for keyword in ("报录比", "竞争比", "竞争热度")):
            return f"{core} 官方公告 报录比 竞争比"
        if any(keyword in normalized for keyword in ("招录人数", "招考人数", "录用人数")):
            return f"{core} 官方公告 招录人数"
        return f"{core} 官方公告 招考简章"

    def _trace_entry(
        self,
        *,
        step: str,
        status: str,
        detail: str,
        started_at: float,
        inputs_summary: dict[str, Any] | None = None,
        outputs_summary: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
        return {
            "step": step,
            "status": status,
            "detail": detail,
            "elapsed_ms": elapsed_ms,
            "inputs_summary": inputs_summary or {},
            "outputs_summary": outputs_summary or {},
            "evidence_refs": evidence_refs or [],
        }

    def _trace_brief(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "step": str(item.get("step") or ""),
            "status": str(item.get("status") or ""),
            "detail": str(item.get("detail") or ""),
            "elapsed_ms": int(item.get("elapsed_ms") or 0),
        }

    def _resolve_model_name(self) -> str | None:
        if self.chat_service is None:
            return None
        client = getattr(self.chat_service, "client", None)
        model_name = getattr(client, "chat_model", None)
        if not model_name:
            return None
        return str(model_name)

    def _serialize_snapshot_row(
        self,
        row: GwyPositionAnalysisSnapshot,
    ) -> dict[str, Any]:
        return {
            "title": row.title,
            "source_sheet": row.source_sheet,
            "filters_json": dict(row.filters_json or {}),
            "snapshot_json": dict(row.snapshot_json or {}),
            "selected_position_ids": list(row.selected_position_ids or []),
            "visible_columns": list(row.visible_columns or []),
            "notes": row.notes or "",
        }

    def _load_user_profile(self, state: PositionAnalysisState) -> dict[str, Any]:
        user_profile = dict(state.get("user_profile") or {})
        if user_profile:
            return user_profile

        if self.session is None or not state.get("user_id"):
            return {}

        user_uuid = UUID(str(state["user_id"]))
        statement = select(GwyUserProfile).where(GwyUserProfile.user_id == user_uuid)
        profile_row = self.session.exec(statement).first()
        if profile_row is None:
            return {}

        return {
            "major": profile_row.major,
            "education": profile_row.education,
            "degree": profile_row.degree,
            "political_status": profile_row.political_status,
            "is_fresh_graduate": profile_row.is_fresh_graduate,
            "grassroots_experience_years": profile_row.grassroots_experience_years,
            "target_regions": list(profile_row.target_regions or []),
            "avoid_conditions": list(profile_row.avoid_conditions or []),
            "desired_departments": list(profile_row.desired_departments or []),
            "desired_positions": list(profile_row.desired_positions or []),
            "excluded_positions": list(profile_row.excluded_positions or []),
            "daily_study_hours": profile_row.daily_study_hours,
            "notes": profile_row.notes,
        }


def _build_evidence_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "doc_title": str(item.get("doc_title") or ""),
        "source_file": str(item.get("source_file") or ""),
        "content": str(item.get("content") or ""),
        "score": float(item.get("score", 0.0) or 0.0),
    }


def _deduplicate_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduplicated: list[dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("id") or ""),
            str(item.get("content") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return deduplicated


def _parse_uuid_list(values: list[Any]) -> list[UUID]:
    parsed: list[UUID] = []
    for value in values:
        try:
            parsed.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return parsed


def _format_json_block(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    payload = str(text or "").strip()
    if not payload:
        return None
    if payload.startswith("```"):
        payload = re.sub(r"^```(?:json)?\s*", "", payload, flags=re.IGNORECASE).strip()
        if payload.endswith("```"):
            payload = payload[:-3].strip()
    start = payload.find("{")
    end = payload.rfind("}")
    if start < 0 or end <= start:
        return None
    snippet = payload[start : end + 1]
    try:
        parsed = json.loads(snippet)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _dedupe_text_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _counter_lines(
    items: list[dict[str, Any]],
    field_name: str,
    label: str,
) -> list[str]:
    counter = Counter(
        str(item.get(field_name) or "未填写").strip() or "未填写"
        for item in items
    )
    if not counter:
        return [f"- {label}: 暂无数据"]
    top_items = ", ".join(f"{key} {count} 条" for key, count in counter.most_common(5))
    return [f"- {label}: {top_items}"]


def _classify_major_requirement(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未填写"
    if any(token in text for token in ("不限", "不限制", "无要求")):
        return "弱限制"
    if any(token in text for token in ("类", "相关", "大类")):
        return "中等限制"
    return "强限制"




