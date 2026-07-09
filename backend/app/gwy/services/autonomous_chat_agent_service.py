from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.gwy.agent_runtime import AgentRuntime, ToolContext, ToolRegistry, ToolSpec
from app.gwy.agent_runtime.builtin_tools import register_builtin_tools
from app.gwy.agent_runtime.trace import TraceEvent, TraceRecorder
from app.gwy.agents.position_decision_agent import PositionDecisionAgent
from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
from app.gwy.agents.risk_review_agent import RiskReviewAgent
from app.gwy.agents.study_plan_agent import StudyPlanAgent
from app.gwy.llm.chat_service import ChatService
from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.models import GwyUserProfile
from app.gwy.skills.policy_rag_skills import build_metadata_filter_skill
from app.gwy.services.agent_memory_service import AgentMemoryService
from app.gwy.services.policy_rag_service import PolicyRagService
from app.gwy.services.position_snapshot_runtime_service import (
    PositionSnapshotRuntimeService,
)
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


AUTONOMOUS_AGENT_SYSTEM_PROMPT = """
你是 GwyPilot 的自主公务员考试助手，工作方式必须接近 learn-claude-code 的 agent loop。

你不能按固定流水线机械执行。你必须根据用户输入自己决定：
1. 是否需要先列计划；
2. 要调用哪些工具；
3. 工具结果是否足够；
4. 是否需要继续检索、核验、生成复习规划或直接回答。

工作规则：
- 对任何非寒暄任务，先调用 `todo_write` 写出 2-5 步计划，并在关键步骤后更新。
- 政策、公告、报考指南、准考证、报名、资格条件、专业目录等问题，调用 `search_policy_knowledge` 检索证据，再调用 `compose_policy_answer` 生成回答。
- 岗位推荐、岗位匹配、备考规划问题，调用 `load_skill` 加载 `position-planning`，再用 `search_positions_pg` 做结构化岗位筛选；不要用 RAG 替代岗位过滤。
- 岗位推荐后，如需要风险或限制核验，调用 `review_position_risks`；如需要复习计划，调用 `generate_study_plan`。
- 最终回答只输出面向用户的中文 Markdown；不要暴露内部 JSON。
- 不要编造政策、岗位条件、时间、分数线或公告来源；证据不足就明确说明。
""".strip()


CLEAN_AUTONOMOUS_AGENT_SYSTEM_PROMPT = """
你是 GwyPilot 的自主公务员考试助手，工作方式必须贴近 learn-claude-code 的 agent loop。
你不能按固定流水线机械执行。你必须根据用户输入自行决定：
1. 是否需要先列计划；
2. 要调用哪些工具；
3. 工具结果是否足够；
4. 是否需要继续检索、核验、生成复习规划或直接回答。

工作规则：
- 对任何非简单任务，先调用 `todo_write` 写出 2-5 步计划，并在关键步骤后更新。
- 政策、公告、报考指南、准考证、报名、资格条件、专业目录等问题，调用 `search_policy_knowledge` 检索证据，再调用 `compose_policy_answer` 生成回答。
- 岗位推荐、岗位匹配、备考规划问题，调用 `load_skill` 加载 `position-planning`，再用 `search_positions_pg` 做结构化岗位筛选；不要用 RAG 替代岗位过滤。
- 岗位推荐后，如需风险或限制核验，调用 `review_position_risks`；如需复习计划，调用 `generate_study_plan`。
- 上下文过长或你需要保留连续性摘要时，可以调用 `compact` 工具，并说明需要保留的重点。
- 最终回答只输出面向用户的中文 Markdown；不要暴露内部 JSON。
- 不要编造政策、岗位条件、时间、分数线或公告来源；证据不足就明确说明。
""".strip()


class AutonomousChatAgentService:
    def __init__(
        self,
        *,
        session: Session,
        chat_service: ChatService | None = None,
    ) -> None:
        self.session = session
        self.chat_service = chat_service or ChatService()
        self.embedding_service = EmbeddingService()
        self.rerank_service = RerankService()
        self.milvus_store = MilvusPolicyStore()
        self.policy_service = PolicyRagService(
            session=session,
            embedding_service=self.embedding_service,
            rerank_service=self.rerank_service,
            chat_service=self.chat_service,
            milvus_store=self.milvus_store,
        )
        self.position_agent = PositionDecisionAgent(
            session=session,
            chat_service=self.chat_service,
        )
        self.risk_review_agent = RiskReviewAgent(
            embedding_service=self.embedding_service,
            rerank_service=self.rerank_service,
            milvus_store=self.milvus_store,
        )
        self.report_generator_agent = ReportGeneratorAgent(
            chat_service=self.chat_service,
        )
        self.study_plan_agent = StudyPlanAgent(chat_service=self.chat_service)

    def run(
        self,
        *,
        query: str,
        user_id: UUID,
        session_id: UUID,
        year: int = 2026,
        exam_type: str = "national",
        top_k: int = 5,
        position_profile: dict[str, Any] | None = None,
        snapshot: dict[str, Any] | None = None,
        position_analysis_task_id: UUID | str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        profile = position_profile or self._load_user_profile(user_id)
        context = {
            "query": query,
            "user_id": str(user_id),
            "session_id": str(session_id),
            "year": year,
            "exam_type": exam_type,
            "top_k": top_k,
            "user_profile": profile,
            "snapshot": dict(snapshot or {}) if snapshot else None,
            "position_analysis_task_id": (
                str(position_analysis_task_id) if position_analysis_task_id else None
            ),
        }
        if self._looks_like_position_recommendation(query):
            if not self._has_snapshot_context(context):
                answer = self._snapshot_guidance_answer()
                return self._snapshot_guidance_result(answer)
            if snapshot:
                return self._run_snapshot_position_analysis(
                    query=query,
                    user_id=user_id,
                    snapshot=snapshot,
                    profile=profile,
                    context=context,
                )

        registry = self._build_tool_registry()
        memory_service = AgentMemoryService(
            session=self.session,
            user_id=user_id,
            conversation_id=str(session_id),
        )
        runtime = AgentRuntime(
            chat_service=self.chat_service,
            tools=registry,
            system_prompt=CLEAN_AUTONOMOUS_AGENT_SYSTEM_PROMPT,
            max_turns=12,
            temperature=0.2,
            on_event=on_event,
            memory_service=memory_service,
        )
        try:
            result = runtime.run(user_prompt=query, context=context)
            state = result.state
            trace = result.trace
            answer = result.answer
        except Exception as exc:
            fallback = self._run_deterministic_fallback(
                query=query,
                context=context,
                error=exc,
                on_event=on_event,
            )
            state = fallback["state"]
            trace = fallback["trace"]
            answer = str(fallback.get("answer") or "")

        report = str(
            state.get("report")
            or state.get("policy_answer")
            or state.get("study_plan_markdown")
            or answer
            or ""
        )
        study_plan = dict(state.get("study_plan") or {})
        study_markdown = str(state.get("study_plan_markdown") or "")
        if study_markdown and study_markdown not in report:
            report = f"{report.rstrip()}\n\n## 复习规划\n\n{study_markdown}".strip()

        report = self.policy_service._normalize_answer_text(report)
        answer = self.policy_service._normalize_answer_text(answer)

        return {
            "answer": report or answer,
            "intent": str(state.get("intent") or "autonomous_agent"),
            "need_rag": bool(state.get("need_rag", True)),
            "decision_branch": "autonomous_agent_runtime",
            "citations": list(state.get("citations") or []),
            "retrieval_trace": trace,
            "rewritten_queries": list(state.get("rewritten_queries") or []),
            "metadata_filter": state.get("metadata_filter"),
            "rerank_results": list(state.get("rerank_results") or []),
            "recommendations": list(state.get("recommendations") or []),
            "risk_review": dict(state.get("risk_review") or {}),
            "report": report,
            "study_plan": study_plan,
            "need_more_info": bool(state.get("need_more_info", False)),
            "missing_fields": list(state.get("missing_fields") or []),
            "recommendation_task_id": state.get("recommendation_task_id"),
            "historical_reference": False,
            "session_attachments": list(state.get("session_attachments") or []),
        }

    def _looks_like_position_recommendation(self, query: str) -> bool:
        keywords = (
            "岗位推荐",
            "推荐岗位",
            "报考岗位",
            "适合什么岗位",
            "岗位分析",
            "职位推荐",
            "公务员岗位",
        )
        return any(keyword in query for keyword in keywords)

    def _has_snapshot_context(self, context: dict[str, Any]) -> bool:
        return bool(
            context.get("snapshot")
            or context.get("position_analysis_task_id")
            or context.get("task_id")
        )

    def _snapshot_guidance_answer(self) -> str:
        return (
            "要做岗位推荐分析，请先在岗位表里筛选岗位并固定快照。"
            "固定快照后，我会基于这批岗位运行同一套 AgentRuntime，"
            "生成岗位分析计划、推荐报告、执行轨迹和复习计划。"
        )

    def _snapshot_guidance_result(self, answer: str) -> dict[str, Any]:
        return {
            "answer": answer,
            "intent": "position_snapshot_required",
            "need_rag": False,
            "decision_branch": "position_snapshot_gate",
            "citations": [],
            "retrieval_trace": [
                {
                    "event": "SnapshotRequired",
                    "status": "done",
                    "step": "position_snapshot_gate",
                    "detail": "Position recommendation requires a fixed snapshot.",
                }
            ],
            "rewritten_queries": [],
            "metadata_filter": None,
            "rerank_results": [],
            "recommendations": [],
            "risk_review": {},
            "report": answer,
            "study_plan": {},
            "need_more_info": False,
            "missing_fields": [],
            "recommendation_task_id": None,
            "historical_reference": False,
            "session_attachments": [],
        }

    def _run_snapshot_position_analysis(
        self,
        *,
        query: str,
        user_id: UUID,
        snapshot: dict[str, Any],
        profile: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        service = PositionSnapshotRuntimeService(
            session=self.session,
            chat_service=self.chat_service,
        )
        result = service.run(
            snapshot=snapshot,
            user_id=user_id,
            user_profile=profile,
            recommendation_context={
                "query": query,
                "year": context.get("year"),
                "exam_type": context.get("exam_type"),
            },
        )
        report = str(result.get("report") or "")
        return {
            "answer": report,
            "intent": "position_recommendation",
            "need_rag": False,
            "decision_branch": "position_snapshot_runtime",
            "citations": [],
            "retrieval_trace": list(result.get("trace") or []),
            "rewritten_queries": [],
            "metadata_filter": None,
            "rerank_results": [],
            "recommendations": list(result.get("recommendations") or []),
            "risk_review": dict(result.get("risk_review") or {}),
            "report": report,
            "study_plan": dict(result.get("study_plan") or {}),
            "need_more_info": bool(result.get("needs_more_info", False)),
            "missing_fields": list(result.get("missing_fields") or []),
            "recommendation_task_id": result.get("task_id"),
            "historical_reference": False,
            "session_attachments": [],
        }

    def _run_deterministic_fallback(
        self,
        *,
        query: str,
        context: dict[str, Any],
        error: Exception,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        recorder = TraceRecorder()
        state = dict(context)
        tool_context = ToolContext(state=state)

        def record(event: TraceEvent) -> None:
            recorder.add(event)
            if on_event is not None:
                on_event(event.to_dict())

        record(
            TraceEvent(
                event="Fallback",
                status="done",
                step="deterministic_policy_fallback",
                detail="Agent tool loop unavailable; running minimal policy fallback.",
                output={"error": str(error), "error_type": error.__class__.__name__},
            )
        )
        try:
            output = self._tool_search_policy_knowledge({"query": query}, tool_context)
            record(
                TraceEvent(
                    event="PostToolUse",
                    status="done",
                    step="search_policy_knowledge",
                    tool="search_policy_knowledge",
                    output=output,
                )
            )
        except Exception as search_exc:
            record(
                TraceEvent(
                    event="ErrorRecovery",
                    status="error",
                    step="search_policy_knowledge",
                    tool="search_policy_knowledge",
                    detail="Policy retrieval failed during fallback; continuing with a safe answer.",
                    output={
                        "error": str(search_exc),
                        "error_type": search_exc.__class__.__name__,
                    },
                )
            )
            state["citations"] = []

        try:
            answer_output = self._tool_compose_policy_answer({"query": query}, tool_context)
        except Exception as answer_exc:
            answer = (
                "当前模型或检索链路暂时不可用，未能完成证据检索和生成。"
                "你可以稍后重试，或补充公告名称、考试年份、地区等信息后再问。"
            )
            state["policy_answer"] = answer
            state["report"] = answer
            answer_output = {
                "answer": answer,
                "error": str(answer_exc),
                "error_type": answer_exc.__class__.__name__,
            }
            record(
                TraceEvent(
                    event="ErrorRecovery",
                    status="done",
                    step="compose_policy_answer",
                    tool="compose_policy_answer",
                    detail="Policy answer generation failed; returned a safe recovery answer.",
                    output=answer_output,
                )
            )
        record(
            TraceEvent(
                event="PostToolUse",
                status="done",
                step="compose_policy_answer",
                tool="compose_policy_answer",
                output=answer_output,
            )
        )
        return {
            "state": state,
            "trace": recorder.to_list(),
            "answer": str(state.get("policy_answer") or ""),
        }

    def _build_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_builtin_tools(registry)
        registry.register(
            ToolSpec(
                name="search_policy_knowledge",
                description=(
                    "Search policy documents, announcements, exam guides, and major catalogs. "
                    "Use this for questions about admission tickets, registration, eligibility, "
                    "exam affairs, policy rules, or official process guidance."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                },
                handler=self._tool_search_policy_knowledge,
            )
        )
        registry.register(
            ToolSpec(
                name="compose_policy_answer",
                description="Compose the final answer for a policy or exam-affairs question using retrieved evidence.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                handler=self._tool_compose_policy_answer,
            )
        )
        registry.register(
            ToolSpec(
                name="search_positions_pg",
                description="Use PostgreSQL structured filters to recommend civil-service positions from the position table.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                },
                handler=self._tool_search_positions_pg,
            )
        )
        registry.register(
            ToolSpec(
                name="review_position_risks",
                description="Review recommended positions for policy and eligibility risks.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                handler=self._tool_review_position_risks,
            )
        )
        registry.register(
            ToolSpec(
                name="generate_study_plan",
                description="Generate a study plan based on the user profile and recommended positions.",
                parameters={
                    "type": "object",
                    "properties": {
                        "study_hours_per_day": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 12,
                        }
                    },
                },
                handler=self._tool_generate_study_plan,
            )
        )
        registry.register(
            ToolSpec(
                name="compose_final_report",
                description="Compose a final Markdown report from recommendations, risks, and study plan.",
                parameters={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
                handler=self._tool_compose_final_report,
            )
        )
        return registry

    def _tool_search_policy_knowledge(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        query = str(args.get("query") or context.state.get("query") or "")
        state = self._policy_state(query=query, context=context, args=args)
        context.record_event(
            event="RetrievalStep",
            status="running",
            step="rewrite_queries",
            tool="search_policy_knowledge",
            detail="Rewriting the user query for policy retrieval.",
            input={"query": query},
        )
        state.update(self.policy_service._node_rewrite_queries(state))
        context.record_event(
            event="RetrievalStep",
            status="done",
            step="rewrite_queries",
            tool="search_policy_knowledge",
            detail="Query rewriting finished.",
            output={"rewritten_queries": list(state.get("rewritten_queries") or [])},
        )
        context.record_event(
            event="RetrievalStep",
            status="running",
            step="retrieve",
            tool="search_policy_knowledge",
            detail="Searching vector store and lexical candidates.",
            output={"metadata_filter": state.get("metadata_filter")},
        )
        state.update(self.policy_service._node_retrieve(state))
        vector_results = list(state.get("vector_results") or [])
        context.record_event(
            event="RetrievalStep",
            status="done",
            step="retrieve",
            tool="search_policy_knowledge",
            detail="Vector and lexical retrieval finished.",
            output={"result_counts": [len(result) for result in vector_results]},
        )
        context.record_event(
            event="RetrievalStep",
            status="running",
            step="fuse_and_rerank",
            tool="search_policy_knowledge",
            detail="Fusing and reranking retrieved evidence.",
        )
        state.update(self.policy_service._node_fuse_and_rerank(state))
        context.record_event(
            event="RetrievalStep",
            status="done",
            step="fuse_and_rerank",
            tool="search_policy_knowledge",
            detail="Evidence fusion and rerank finished.",
            output={
                "rerank_count": len(list(state.get("rerank_results") or [])),
                "citation_count": len(list(state.get("citations") or [])),
            },
        )
        context.record_event(
            event="RetrievalStep",
            status="running",
            step="react_evidence_review",
            tool="search_policy_knowledge",
            detail="Checking whether retrieved evidence is sufficient.",
        )
        state.update(self.policy_service._node_react_evidence_review(state))
        context.record_event(
            event="RetrievalStep",
            status="done",
            step="react_evidence_review",
            tool="search_policy_knowledge",
            detail="Evidence review finished.",
            output={"citation_count": len(list(state.get("citations") or []))},
        )

        citations = list(state.get("citations") or [])
        context.state["citations"] = citations
        context.state["rewritten_queries"] = list(state.get("rewritten_queries") or [])
        context.state["rerank_results"] = list(state.get("rerank_results") or [])
        context.state["metadata_filter"] = state.get("metadata_filter")
        context.state["policy_trace"] = list(state.get("retrieval_trace") or [])
        context.state["need_rag"] = True
        context.state["intent"] = "policy_rag"

        return {
            "citation_count": len(citations),
            "rewritten_queries": context.state["rewritten_queries"],
            "citations": [self._citation_preview(item) for item in citations[:5]],
        }

    def _tool_compose_policy_answer(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        query = str(args.get("query") or context.state.get("query") or "")
        citations = list(context.state.get("citations") or [])
        if not citations:
            self._tool_search_policy_knowledge({"query": query}, context)
            citations = list(context.state.get("citations") or [])

        state = self._policy_state(query=query, context=context, args=args)
        state["citations"] = citations
        state["rewritten_queries"] = list(context.state.get("rewritten_queries") or [])
        state["rerank_results"] = list(context.state.get("rerank_results") or [])
        state["metadata_filter"] = context.state.get("metadata_filter")
        prompt = self.policy_service._build_answer_prompt(state, citations)
        answer = self.policy_service._generate_answer(prompt, citations)
        context.state["policy_answer"] = answer
        context.state["report"] = answer
        context.state["intent"] = "policy_rag"
        return {
            "answer": answer,
            "citation_count": len(citations),
        }

    def _policy_state(
        self,
        *,
        query: str,
        context: ToolContext,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        session_id = UUID(str(context.state["session_id"]))
        user_id = UUID(str(context.state["user_id"]))
        try:
            memory_context = self.policy_service.session_service.get_memory_context(
                session_id=session_id,
                user_id=user_id,
            )
        except Exception:
            memory_context = None
        try:
            attachments = self.policy_service._load_session_attachments(
                session_id=session_id,
                user_id=user_id,
            )
        except Exception:
            attachments = []
        year = int(context.state.get("year") or 2026)
        exam_type = str(context.state.get("exam_type") or "national")
        doc_group = args.get("doc_group")
        doc_type = args.get("doc_type")
        metadata_filter = build_metadata_filter_skill(
            year=year,
            exam_type=exam_type,
            intent="policy_qa",
            doc_group=str(doc_group) if doc_group else None,
            doc_type=str(doc_type) if doc_type else None,
        )
        return {
            "query": query,
            "session_id": str(session_id),
            "user_id": str(user_id),
            "intent": "policy_qa",
            "need_rag": True,
            "decision_branch": "autonomous_policy_rag",
            "year": year,
            "exam_type": exam_type,
            "doc_group": doc_group,
            "doc_type": doc_type,
            "metadata_filter": metadata_filter,
            "top_k": int(args.get("top_k") or context.state.get("top_k") or 5),
            "use_rerank": True,
            "retrieval_trace": [],
            "memory_context": memory_context,
            "session_attachments": attachments,
        }

    def _tool_search_positions_pg(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        query = str(args.get("query") or context.state.get("query") or "")
        top_k = int(args.get("top_k") or context.state.get("top_k") or 5)
        result = self.position_agent.run(
            query=query,
            user_id=UUID(str(context.state["user_id"])),
            session_id=UUID(str(context.state["session_id"])),
            year=int(context.state.get("year") or 2026),
            exam_type=str(context.state.get("exam_type") or "national"),
            top_k=top_k,
            persist_result=True,
            profile_override=dict(context.state.get("user_profile") or {}),
        )
        context.state["recommendations"] = list(result.get("recommendations") or [])
        context.state["recommendation_summary"] = dict(result.get("summary") or {})
        context.state["recommendation_task_id"] = result.get("task_id")
        context.state["need_more_info"] = bool(result.get("need_more_info", False))
        context.state["missing_fields"] = list(result.get("missing_fields") or [])
        context.state["intent"] = "position_recommendation"
        return {
            "recommendations": context.state["recommendations"],
            "summary": context.state["recommendation_summary"],
            "need_more_info": context.state["need_more_info"],
            "missing_fields": context.state["missing_fields"],
        }

    def _tool_review_position_risks(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        recommendations = list(context.state.get("recommendations") or [])
        result = self.risk_review_agent.run(
            query=str(args.get("query") or context.state.get("query") or ""),
            recommendations=recommendations,
        )
        context.state["risk_review"] = dict(result)
        return dict(result)

    def _tool_generate_study_plan(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        profile = dict(context.state.get("user_profile") or {})
        recommendations = list(context.state.get("recommendations") or [])
        hours = int(args.get("study_hours_per_day") or profile.get("daily_study_hours") or 4)
        result = self.study_plan_agent.run(
            user_profile=profile,
            recommendations=recommendations,
            exam_type=str(context.state.get("exam_type") or "national"),
            exam_year=int(context.state.get("year") or 2026),
            study_hours_per_day=hours,
        )
        context.state["study_plan"] = dict(result)
        context.state["study_plan_markdown"] = str(result.get("plan_markdown") or "")
        return {
            "plan_title": result.get("plan_title"),
            "total_weeks": result.get("total_weeks"),
            "plan_markdown": context.state["study_plan_markdown"],
        }

    def _tool_compose_final_report(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        title = str(args.get("title") or "岗位推荐与复习规划报告")
        result = self.report_generator_agent.run(
            title=title,
            recommendations=list(context.state.get("recommendations") or []),
            risk_review=dict(context.state.get("risk_review") or {}),
        )
        report = str(result.get("report") or "")
        study_markdown = str(context.state.get("study_plan_markdown") or "")
        if study_markdown:
            report = f"{report.rstrip()}\n\n## 复习规划\n\n{study_markdown}".strip()
        context.state["report"] = report
        return {"report": report, "report_meta": dict(result.get("report_meta") or {})}

    def _citation_preview(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": item.get("doc_title") or item.get("source_file") or "未命名来源",
            "section": item.get("section"),
            "score": item.get("rerank_score", item.get("score")),
            "excerpt": self.policy_service._excerpt(
                str(
                    item.get("content_excerpt")
                    or item.get("content")
                    or item.get("summary")
                    or ""
                ),
                limit=240,
            ),
        }

    def _load_user_profile(self, user_id: UUID) -> dict[str, Any]:
        row = self.session.exec(
            select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        ).first()
        if row is None:
            return {}
        return {
            "name": row.name,
            "nickname": row.nickname,
            "education": row.education,
            "degree": row.degree,
            "major": row.major,
            "political_status": row.political_status,
            "is_fresh_graduate": row.is_fresh_graduate,
            "grassroots_experience_years": row.grassroots_experience_years,
            "target_regions": list(row.target_regions or []),
            "avoid_conditions": list(row.avoid_conditions or []),
            "desired_departments": list(row.desired_departments or []),
            "desired_positions": list(row.desired_positions or []),
            "excluded_positions": list(row.excluded_positions or []),
            "daily_study_hours": row.daily_study_hours,
            "notes": row.notes,
        }
