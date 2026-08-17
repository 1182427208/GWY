from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlmodel import Session, select

from app.gwy.agents.feishu_push_agent import FeishuPushAgent
from app.gwy.agents.position_decision_agent import PositionDecisionAgent
from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
from app.gwy.agents.risk_review_agent import RiskReviewAgent
from app.gwy.llm.chat_service import ChatService
from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.multimodal_service import MultimodalSummaryService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.models import GwyUserProfile
from app.gwy.prompts.policy_rag import (
    DIRECT_ANSWER_SYSTEM_PROMPT,
    DIRECT_ANSWER_USER_PROMPT_TEMPLATE,
    POLICY_RAG_SYSTEM_PROMPT,
    POLICY_RAG_USER_PROMPT_TEMPLATE,
)
from app.gwy.services.agent_memory_service import AgentMemoryService
from app.gwy.services.chat_session_service import ChatSessionService
from app.gwy.services.hybrid_retrieval_service import HybridRetrievalService
from app.gwy.services.memory_side_query_service import MemorySideQueryService
from app.gwy.skills.policy_rag_skills import (
    build_cache_key,
    build_doc_title_hint,
    build_metadata_filter_skill,
    build_rewritten_queries_skill,
    build_session_title_skill,
    route_intent_skill,
    rrf_fusion_skill,
    unique_citation_docs_skill,
    unique_queries_skill,
)
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


class PolicyRagState(TypedDict, total=False):
    query: str
    session_id: str | None
    user_id: str | None
    year: int
    exam_type: str
    doc_group: str | None
    doc_type: str | None
    top_k: int
    use_rerank: bool
    mode: str | None
    intent_hint: str | None
    position_profile: dict[str, Any] | None
    intent: str
    need_rag: bool
    metadata_filter: str | None
    rewritten_queries: list[str]
    retrieval_trace: list[dict[str, Any]]
    vector_results: list[list[dict[str, Any]]]
    hybrid_results: list[dict[str, Any]]
    fused_results: list[dict[str, Any]]
    rerank_results: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    risk_review: dict[str, Any]
    report: str
    feishu_push: dict[str, Any] | None
    need_more_info: bool
    missing_fields: list[str]
    recommendation_task_id: str | None
    decision_branch: str
    citations: list[dict[str, Any]]
    session_attachments: list[dict[str, Any]]
    memory_context: dict[str, Any]
    answer: str
    historical_reference: bool


@dataclass(slots=True)
class RetrievalCandidate:
    content: str
    score: float
    metadata: dict[str, Any]
    source_query: str
    chunk_id: str | None = None


class PolicyRagService:
    def __init__(
        self,
        *,
        session: Session | None = None,
        embedding_service: EmbeddingService | None = None,
        rerank_service: RerankService | None = None,
        chat_service: ChatService | None = None,
        milvus_store: MilvusPolicyStore | None = None,
        session_service: ChatSessionService | None = None,
        feishu_push_agent: FeishuPushAgent | None = None,
    ) -> None:
        self.session = session
        self.embedding_service = embedding_service or EmbeddingService()
        self.rerank_service = rerank_service or RerankService()
        self.chat_service = chat_service or ChatService()
        self.milvus_store = milvus_store or MilvusPolicyStore()
        self.hybrid_retrieval_service = HybridRetrievalService()
        self.session_service = session_service or self._build_session_service()
        self.position_agent = (
            PositionDecisionAgent(session=self.session, chat_service=self.chat_service)
            if self.session is not None
            else None
        )
        self.risk_review_agent = RiskReviewAgent(
            embedding_service=self.embedding_service,
            rerank_service=self.rerank_service,
            milvus_store=self.milvus_store,
        )
        self.report_generator_agent = ReportGeneratorAgent(
            chat_service=self.chat_service,
        )
        self.feishu_push_agent = feishu_push_agent or FeishuPushAgent()
        self.graph = self._build_graph()

    def query_policy(
        self,
        *,
        query: str,
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        year: int = 2026,
        exam_type: str = "national",
        doc_group: str | None = None,
        doc_type: str | None = None,
        top_k: int = 6,
        use_rerank: bool = True,
        mode: str | None = None,
        intent_hint: str | None = None,
        position_profile: dict[str, Any] | None = None,
        memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state: PolicyRagState = {
            "query": query,
            "session_id": str(session_id) if session_id else None,
            "user_id": str(user_id) if user_id else None,
            "year": year,
            "exam_type": exam_type,
            "doc_group": doc_group,
            "doc_type": doc_type,
            "top_k": top_k,
            "use_rerank": use_rerank,
            "mode": mode,
            "intent_hint": intent_hint,
            "position_profile": position_profile,
            "retrieval_trace": [],
        }
        if session_id is not None and user_id is not None:
            state["memory_context"] = memory_context or self._load_side_query_memory(
                query=query,
                session_id=session_id,
                user_id=user_id,
            )
        if session_id is not None and user_id is not None:
            state["session_attachments"] = self._load_session_attachments(
                session_id=session_id,
                user_id=user_id,
            )
        return self.graph.invoke(state)

    def stream_chat_message(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        query: str,
        year: int = 2026,
        exam_type: str = "national",
        doc_group: str | None = None,
        doc_type: str | None = None,
        top_k: int = 6,
        use_rerank: bool = True,
        mode: str | None = None,
        intent_hint: str | None = None,
        position_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chat_session = self.session_service.get_session(session_id, user_id)
        user_message = self.session_service.append_message(
            session_id=session_id,
            role="user",
            content=query,
        )

        state = self.prepare_policy_state(
            query=query,
            session_id=session_id,
            user_id=user_id,
            year=year,
            exam_type=exam_type,
            doc_group=doc_group,
            doc_type=doc_type,
            top_k=top_k,
            use_rerank=use_rerank,
            mode=mode,
            intent_hint=intent_hint,
            position_profile=position_profile,
        )

        if str(state.get("intent") or "") == "position_recommendation":
            position_started_at = time.perf_counter()
            current_stage = "position_recommendation"
            yield _sse_stage_event(
                "position_recommendation",
                "running",
                detail="正在基于岗位表筛选适合的岗位",
                elapsed_ms=0,
            )
            state.update(service._node_position_recommendation(state))
            yield _sse_stage_event(
                "position_recommendation",
                "done",
                detail="已完成岗位筛选与推荐",
                elapsed_ms=_elapsed_ms(position_started_at),
            )
            answer = service._normalize_answer_text(str(state.get("answer") or ""))
            if answer.strip():
                answer_parts.append(answer)
                yield _sse_event("delta", {"delta": answer})
            yield _sse_event(
                "meta",
                {
                    "session_id": str(session_id),
                    "intent": state.get("intent"),
                    "need_rag": bool(state.get("need_rag", True)),
                    "recommendation_count": len(state.get("recommendations") or []),
                },
            )
        elif bool(state.get("need_rag", True)):
            yield _sse_stage_event(
                "rewrite_queries",
                "running",
                detail="正在改写问题，准备检索",
                elapsed_ms=0,
            )
            current_stage = "rewrite_queries"
            rewrite_started_at = time.perf_counter()
            state.update(service._node_rewrite_queries(state))
            yield _sse_stage_event(
                "rewrite_queries",
                "done",
                detail="已完成问题改写",
                elapsed_ms=_elapsed_ms(rewrite_started_at),
            )

            retrieve_started_at = time.perf_counter()
            yield _sse_stage_event(
                "retrieve",
                "running",
                detail="正在检索相关政策材料",
                elapsed_ms=0,
            )
            current_stage = "retrieve"
            state.update(service._node_retrieve(state))
            yield _sse_stage_event(
                "retrieve",
                "done",
                detail="已完成知识检索",
                elapsed_ms=_elapsed_ms(retrieve_started_at),
            )

            rerank_started_at = time.perf_counter()
            yield _sse_stage_event(
                "fuse_and_rerank",
                "running",
                detail="正在融合结果并进行重排",
                elapsed_ms=0,
            )
            current_stage = "fuse_and_rerank"
            state.update(service._node_fuse_and_rerank(state))
            yield _sse_stage_event(
                "fuse_and_rerank",
                "done",
                detail="已完成融合与重排",
                elapsed_ms=_elapsed_ms(rerank_started_at),
            )

            citations = list(state.get("citations") or [])
            yield _sse_event(
                "meta",
                {
                    "session_id": str(session_id),
                    "intent": state.get("intent"),
                    "need_rag": bool(state.get("need_rag", True)),
                    "citation_count": len(citations),
                },
            )
            prompt = service._build_answer_prompt(state, citations)
            yield _sse_stage_event(
                "answer",
                "running",
                detail="正在生成基于证据的回答",
                elapsed_ms=0,
            )
            answer_started_at = time.perf_counter()
            try:
                current_stage = "answer"
                stream = service.chat_service.stream_chat_completion(
                    [
                        {"role": "system", "content": POLICY_RAG_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                yield from stream_model_output(stream)
            except Exception:
                fallback_answer = service._generate_answer(prompt, citations)
                answer_parts = [fallback_answer]
                yield _sse_event("delta", {"delta": fallback_answer})
            yield _sse_stage_event(
                "answer",
                "done",
                detail="已完成回答生成",
                elapsed_ms=_elapsed_ms(answer_started_at),
            )
        else:
            yield _sse_event(
                "meta",
                {
                    "session_id": str(session_id),
                    "intent": state.get("intent"),
                    "need_rag": bool(state.get("need_rag", True)),
                    "citation_count": 0,
                },
            )
            prompt = service._build_direct_answer_prompt(state)
            yield _sse_stage_event(
                "direct_answer",
                "running",
                detail="正在生成直接回答",
                elapsed_ms=0,
            )
            answer_started_at = time.perf_counter()
            try:
                stream = service.chat_service.stream_chat_completion(
                    [
                        {"role": "system", "content": DIRECT_ANSWER_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                yield from stream_model_output(stream)
            except Exception:
                fallback_answer = service._generate_direct_answer(prompt, state)
                answer_parts = [fallback_answer]
                yield _sse_event("delta", {"delta": fallback_answer})
            yield _sse_stage_event(
                "direct_answer",
                "done",
                detail="已完成直接回答生成",
                elapsed_ms=_elapsed_ms(answer_started_at),
            )
        answer = service._normalize_answer_text("".join(answer_parts))
        result = self._build_result_payload(state, answer)

        assistant_message = self.session_service.append_message(
            session_id=session_id,
            role="assistant",
            content=str(result.get("answer", "")),
            intent=str(result.get("intent") or "unknown"),
            historical_reference=bool(result.get("historical_reference", False)),
            citations=list(result.get("citations") or []),
            retrieval_trace=list(result.get("retrieval_trace") or []),
            metadata_json={
                "rewritten_queries": list(result.get("rewritten_queries") or []),
                "metadata_filter": result.get("metadata_filter"),
                "rerank_results": list(result.get("rerank_results") or []),
                "recommendations": list(result.get("recommendations") or []),
                "decision_branch": result.get("decision_branch"),
                "need_more_info": bool(result.get("need_more_info", False)),
                "missing_fields": list(result.get("missing_fields") or []),
                "recommendation_task_id": result.get("recommendation_task_id"),
                "risk_review": dict(result.get("risk_review") or {}),
                "report": str(result.get("report") or ""),
                "feishu_push": dict(result.get("feishu_push") or {}),
                "session_attachment_count": len(
                    list(result.get("session_attachments") or [])
                ),
                "memory_context": state.get("memory_context") or {},
            },
        )

        messages = self.session_service.list_messages(session_id, user_id)
        summary = self.session_service.build_session_summary(messages)
        mentioned_docs = self._extract_mentioned_docs(result.get("citations") or [])
        topic = build_doc_title_hint(str(result.get("intent") or "")) or str(
            result.get("intent") or "unknown"
        )
        updated_session = self.session_service.update_session_state(
            session_id=session_id,
            user_id=user_id,
            title=chat_session.title
            if chat_session.title != "新会话"
            else self._build_session_title(query, result),
            summary=summary,
            last_intent=str(result.get("intent") or "unknown"),
            active_topic=topic,
            mentioned_docs=mentioned_docs,
        )
        self.session_service.consume_attachments(session_id, user_id)

        return {
            **result,
            "session": self._serialize_session(updated_session),
            "user_message": self._serialize_message(user_message),
            "assistant_message": self._serialize_message(assistant_message),
        }

    def prepare_policy_state(
        self,
        *,
        query: str,
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        year: int = 2026,
        exam_type: str = "national",
        doc_group: str | None = None,
        doc_type: str | None = None,
        top_k: int = 6,
        use_rerank: bool = True,
        mode: str | None = None,
        intent_hint: str | None = None,
        position_profile: dict[str, Any] | None = None,
        memory_context: dict[str, Any] | None = None,
    ) -> PolicyRagState:
        state: PolicyRagState = {
            "query": query,
            "session_id": str(session_id) if session_id else None,
            "user_id": str(user_id) if user_id else None,
            "year": year,
            "exam_type": exam_type,
            "doc_group": doc_group,
            "doc_type": doc_type,
            "top_k": top_k,
            "use_rerank": use_rerank,
            "mode": mode,
            "intent_hint": intent_hint,
            "position_profile": position_profile,
            "retrieval_trace": [],
        }
        if session_id is not None and user_id is not None:
            state["memory_context"] = memory_context or self._load_side_query_memory(
                query=query,
                session_id=session_id,
                user_id=user_id,
            )
            state["session_attachments"] = self._load_session_attachments(
                session_id=session_id,
                user_id=user_id,
            )
        state.update(self._node_route_intent(state))
        if not bool(state.get("need_rag", True)):
            return state
        state.update(self._node_rewrite_queries(state))
        state.update(self._node_retrieve(state))
        state.update(self._node_fuse_and_rerank(state))
        state.update(self._node_react_evidence_review(state))
        return state

    def _load_side_query_memory(
        self,
        *,
        query: str,
        session_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        """Load only side-query-selected memory into policy prompts."""
        try:
            memory_service = AgentMemoryService(
                session=self.session,
                user_id=user_id,
                conversation_id=str(session_id),
            )
            side_query = MemorySideQueryService(chat_service=self.chat_service)
            result = side_query.retrieve(
                query=query,
                cards=memory_service.build_memory_catalog(),
            )
            memory_text = str(result.get("memory_text") or "").strip()
            if not memory_text:
                return {}
            return {
                "side_query_memory_text": memory_text,
                "side_query_selected_names": list(
                    result.get("selected_names") or []
                ),
            }
        except Exception:
            # Memory is optional for policy answering; retrieval failures must
            # never block the primary RAG flow or trigger direct-memory fallback.
            return {}

    def _build_result_payload(
        self,
        state: PolicyRagState,
        answer: str,
    ) -> dict[str, Any]:
        return {
            "answer": self._normalize_answer_text(answer),
            "intent": str(state.get("intent") or "unknown"),
            "need_rag": bool(state.get("need_rag", True)),
            "decision_branch": str(
                state.get("decision_branch")
                or (
                    "postgresql_position_recommendation"
                    if str(state.get("intent") or "") == "position_recommendation"
                    else (
                        "policy_rag"
                        if bool(state.get("need_rag", True))
                        else "direct_answer"
                    )
                )
            ),
            "citations": list(state.get("citations") or []),
            "retrieval_trace": list(state.get("retrieval_trace") or []),
            "rewritten_queries": list(state.get("rewritten_queries") or []),
            "metadata_filter": state.get("metadata_filter"),
            "rerank_results": list(state.get("rerank_results") or []),
            "recommendations": list(state.get("recommendations") or []),
            "need_more_info": bool(state.get("need_more_info", False)),
            "missing_fields": list(state.get("missing_fields") or []),
            "recommendation_task_id": state.get("recommendation_task_id"),
            "risk_review": dict(state.get("risk_review") or {}),
            "report": str(state.get("report") or ""),
            "feishu_push": dict(state.get("feishu_push") or {}),
            "historical_reference": bool(state.get("historical_reference", False)),
            "session_attachments": list(state.get("session_attachments") or []),
        }

    def finalize_chat_turn(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        query: str,
        user_message: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        chat_session = self.session_service.get_session(session_id, user_id)
        assistant_message = self.session_service.append_message(
            session_id=session_id,
            role="assistant",
            content=str(result.get("answer", "")),
            intent=str(result.get("intent") or "unknown"),
            historical_reference=bool(result.get("historical_reference", False)),
            citations=list(result.get("citations") or []),
            retrieval_trace=list(result.get("retrieval_trace") or []),
            metadata_json={
                "rewritten_queries": list(result.get("rewritten_queries") or []),
                "metadata_filter": result.get("metadata_filter"),
                "rerank_results": list(result.get("rerank_results") or []),
                "recommendations": list(result.get("recommendations") or []),
                "decision_branch": result.get("decision_branch"),
                "need_more_info": bool(result.get("need_more_info", False)),
                "missing_fields": list(result.get("missing_fields") or []),
                "recommendation_task_id": result.get("recommendation_task_id"),
                "risk_review": dict(result.get("risk_review") or {}),
                "report": str(result.get("report") or ""),
                "feishu_push": dict(result.get("feishu_push") or {}),
                "session_attachment_count": len(
                    list(result.get("session_attachments") or [])
                ),
            },
        )
        messages = self.session_service.list_messages(session_id, user_id)
        summary = self.session_service.build_session_summary(messages)
        mentioned_docs = self._extract_mentioned_docs(result.get("citations") or [])
        topic = build_doc_title_hint(str(result.get("intent") or "")) or str(
            result.get("intent") or "unknown"
        )
        updated_session = self.session_service.update_session_state(
            session_id=session_id,
            user_id=user_id,
            title=chat_session.title
            if chat_session.title != "新会话"
            else self._build_session_title(query, result),
            summary=summary,
            last_intent=str(result.get("intent") or "unknown"),
            active_topic=topic,
            mentioned_docs=mentioned_docs,
        )
        self.session_service.consume_attachments(session_id, user_id)
        return {
            **result,
            "session": self._serialize_session(updated_session),
            "user_message": user_message,
            "assistant_message": self._serialize_message(assistant_message),
        }

    def answer_chat_message(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        query: str,
        year: int = 2026,
        exam_type: str = "national",
        doc_group: str | None = None,
        doc_type: str | None = None,
        top_k: int = 6,
        use_rerank: bool = True,
        mode: str | None = None,
        intent_hint: str | None = None,
        position_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chat_session = self.session_service.get_session(session_id, user_id)
        user_message = self.session_service.append_message(
            session_id=session_id,
            role="user",
            content=query,
        )
        result = self.query_policy(
            query=query,
            session_id=session_id,
            user_id=user_id,
            year=year,
            exam_type=exam_type,
            doc_group=doc_group,
            doc_type=doc_type,
            top_k=top_k,
            use_rerank=use_rerank,
            mode=mode,
            intent_hint=intent_hint,
            position_profile=position_profile,
        )

        assistant_message = self.session_service.append_message(
            session_id=session_id,
            role="assistant",
            content=str(result.get("answer", "")),
            intent=str(result.get("intent") or "unknown"),
            historical_reference=bool(result.get("historical_reference", False)),
            citations=list(result.get("citations") or []),
            retrieval_trace=list(result.get("retrieval_trace") or []),
            metadata_json={
                "rewritten_queries": list(result.get("rewritten_queries") or []),
                "metadata_filter": result.get("metadata_filter"),
                "rerank_results": list(result.get("rerank_results") or []),
                "recommendations": list(result.get("recommendations") or []),
                "decision_branch": result.get("decision_branch"),
                "need_more_info": bool(result.get("need_more_info", False)),
                "missing_fields": list(result.get("missing_fields") or []),
                "recommendation_task_id": result.get("recommendation_task_id"),
                "feishu_push": dict(result.get("feishu_push") or {}),
                "session_attachment_count": len(
                    list(result.get("session_attachments") or [])
                ),
            },
        )

        messages = self.session_service.list_messages(session_id, user_id)
        summary = self.session_service.build_session_summary(messages)
        mentioned_docs = self._extract_mentioned_docs(result.get("citations") or [])
        topic = build_doc_title_hint(str(result.get("intent") or "")) or str(
            result.get("intent") or "unknown"
        )
        updated_session = self.session_service.update_session_state(
            session_id=session_id,
            user_id=user_id,
            title=chat_session.title
            if chat_session.title != "新会话"
            else self._build_session_title(query, result),
            summary=summary,
            last_intent=str(result.get("intent") or "unknown"),
            active_topic=topic,
            mentioned_docs=mentioned_docs,
        )

        return {
            **result,
            "session": self._serialize_session(updated_session),
            "user_message": self._serialize_message(user_message),
            "assistant_message": self._serialize_message(assistant_message),
        }

    def _build_graph(self) -> Any:
        builder = StateGraph(PolicyRagState)
        builder.add_node("route_intent", self._node_route_intent)
        builder.add_node(
            "position_recommendation", self._node_position_recommendation
        )
        builder.add_node("direct_answer", self._node_direct_answer)
        builder.add_node("rewrite_queries", self._node_rewrite_queries)
        builder.add_node("retrieve", self._node_retrieve)
        builder.add_node("fuse_and_rerank", self._node_fuse_and_rerank)
        builder.add_node(
            "react_evidence_review", self._node_react_evidence_review
        )
        builder.add_node("answer", self._node_answer)
        builder.add_edge(START, "route_intent")
        builder.add_conditional_edges(
            "route_intent",
            self._route_after_intent,
            {
                "position_recommendation": "position_recommendation",
                "direct_answer": "direct_answer",
                "rewrite_queries": "rewrite_queries",
            },
        )
        builder.add_edge("position_recommendation", END)
        builder.add_edge("direct_answer", END)
        builder.add_edge("rewrite_queries", "retrieve")
        builder.add_edge("retrieve", "fuse_and_rerank")
        builder.add_edge("fuse_and_rerank", "react_evidence_review")
        builder.add_edge("react_evidence_review", "answer")
        builder.add_edge("answer", END)
        return builder.compile()

    def _node_route_intent(self, state: PolicyRagState) -> dict[str, Any]:
        if self._is_explicit_position_mode(state):
            trace = list(state.get("retrieval_trace") or [])
            trace.append(
                {
                    "step": "intent_routing",
                    "intent": "position_recommendation",
                    "doc_group": "position_table",
                    "doc_type": "position_recommendation",
                    "need_rag": False,
                    "mode": state.get("mode"),
                    "intent_hint": state.get("intent_hint"),
                    "route_source": "explicit_mode",
                }
            )
            return {
                "intent": "position_recommendation",
                "need_rag": False,
                "doc_group": "position_table",
                "doc_type": "position_recommendation",
                "metadata_filter": None,
                "retrieval_trace": trace,
            }
        routed = route_intent_skill(state["query"])
        intent = str(routed["intent"])
        doc_group = str(state.get("doc_group") or routed["doc_group"])
        doc_type = str(state.get("doc_type") or routed["doc_type"])
        metadata_filter = build_metadata_filter_skill(
            year=state["year"],
            exam_type=state["exam_type"],
            intent=intent,
            doc_group=doc_group,
            doc_type=doc_type,
        )
        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "intent_routing",
                "intent": intent,
                "doc_group": doc_group,
                "doc_type": doc_type,
                "need_rag": bool(routed["need_rag"]),
            }
        )
        return {
            "intent": intent,
            "need_rag": bool(routed["need_rag"]),
            "doc_group": doc_group,
            "doc_type": doc_type,
            "metadata_filter": metadata_filter,
            "retrieval_trace": trace,
        }

    def _route_after_intent(self, state: PolicyRagState) -> str:
        if str(state.get("intent") or "") == "position_recommendation":
            return "position_recommendation"
        return "direct_answer" if not bool(state.get("need_rag", True)) else "rewrite_queries"

    def _node_position_recommendation(self, state: PolicyRagState) -> dict[str, Any]:
        if self.position_agent is None:
            raise RuntimeError("Position recommendation agent is unavailable.")

        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "position_recommendation",
                "stage": "start",
            }
        )
        result = self.position_agent.run(
            query=state["query"],
            user_id=UUID(state["user_id"]) if state.get("user_id") else None,
            session_id=UUID(state["session_id"]) if state.get("session_id") else None,
            year=state["year"],
            exam_type=state["exam_type"],
            top_k=state["top_k"],
            profile_override=state.get("position_profile"),
        )
        trace.extend(list(result.get("retrieval_trace") or []))
        trace.append(
            {
                "step": "position_recommendation",
                "stage": "done",
                "recommendation_count": len(result.get("recommendations") or []),
            }
        )
        risk_review_result = self.risk_review_agent.run(
            query=state["query"],
            recommendations=list(result.get("recommendations") or []),
        )
        trace.extend(list(risk_review_result.get("trace") or []))
        report_result = self.report_generator_agent.run(
            title=self._build_position_report_title(state),
            recommendations=list(result.get("recommendations") or []),
            risk_review=risk_review_result,
        )
        trace.extend(list(report_result.get("trace") or []))
        feishu_push_result = self._push_report_to_feishu(
            title=self._build_position_report_title(state),
            report_text=str(report_result.get("report") or ""),
            task_id=str(result.get("task_id") or ""),
            user_id=state.get("user_id"),
        )
        if feishu_push_result is not None:
            trace.append(
                {
                    "step": "feishu_push",
                    "status": str(feishu_push_result.get("status") or "unknown"),
                    "error_message": feishu_push_result.get("error_message"),
                }
            )
        return {
            "answer": result.get("answer", ""),
            "citations": [],
            "rerank_results": [],
            "recommendations": list(result.get("recommendations") or []),
            "risk_review": dict(risk_review_result),
            "report": str(report_result.get("report") or ""),
            "feishu_push": feishu_push_result,
            "need_more_info": bool(result.get("need_more_info", False)),
            "missing_fields": list(result.get("missing_fields") or []),
            "recommendation_task_id": result.get("task_id"),
            "decision_branch": "postgresql_position_recommendation",
            "retrieval_trace": trace,
            "historical_reference": False,
        }

    def _build_position_report_title(self, state: PolicyRagState) -> str:
        exam_year = state.get("year") or 2026
        exam_type = str(state.get("exam_type") or "national")
        return f"{exam_year}年{exam_type}岗位推荐报告"

    def _push_report_to_feishu(
        self,
        *,
        title: str,
        report_text: str,
        task_id: str | None,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        if self.feishu_push_agent is None:
            return None

        webhook_url = self._resolve_feishu_webhook_url(user_id)
        if not webhook_url:
            return {
                "status": "skipped",
                "error_message": "Feishu webhook is not configured for this user.",
                "response_json": {},
                "trace": [
                    {
                        "step": "plan",
                        "status": "skipped",
                        "reason": "webhook_missing",
                    },
                    {
                        "step": "push",
                        "status": "skipped",
                        "reason": "webhook_missing",
                    },
                    {
                        "step": "reflect",
                        "status": "skipped",
                        "has_response": False,
                    },
                ],
            }

        push_result = self.feishu_push_agent.run(
            report_kind="recommendation",
            title=title,
            report_text=report_text,
            task_id=task_id,
            webhook_url=webhook_url,
        )
        return {
            "status": str(push_result.get("status") or "unknown"),
            "error_message": push_result.get("error_message"),
            "response_json": dict(push_result.get("response_json") or {}),
            "trace": list(push_result.get("trace") or []),
        }

    def _resolve_feishu_webhook_url(self, user_id: str | None) -> str | None:
        if not user_id:
            return str(getattr(settings, "FEISHU_WEBHOOK_URL", "") or "").strip() or None
        try:
            user_uuid = UUID(user_id)
        except (TypeError, ValueError):
            return str(getattr(settings, "FEISHU_WEBHOOK_URL", "") or "").strip() or None
        profile = self.session.exec(
            select(GwyUserProfile).where(GwyUserProfile.user_id == user_uuid)
        ).first()
        webhook_url = str(profile.feishu_webhook_url or "").strip() if profile else ""
        if not webhook_url:
            webhook_url = str(getattr(settings, "FEISHU_WEBHOOK_URL", "") or "").strip()
        return webhook_url or None

    def _is_explicit_position_mode(self, state: PolicyRagState) -> bool:
        mode = str(state.get("mode") or "").strip().lower()
        if mode == "position_recommendation":
            return True
        intent_hint = str(state.get("intent_hint") or "").strip().lower()
        return intent_hint == "position_recommendation"

    def _node_direct_answer(self, state: PolicyRagState) -> dict[str, Any]:
        trace = list(state.get("retrieval_trace") or [])
        prompt = self._build_direct_answer_prompt(state)
        answer = self._generate_direct_answer(prompt, state)
        trace.append(
            {
                "step": "direct_answer",
                "mode": "no_rag",
                "used_llm": bool(answer.strip()),
            }
        )
        return {
            "answer": answer,
            "citations": [],
            "rerank_results": [],
            "retrieval_trace": trace,
            "historical_reference": False,
            "session_attachments": list(state.get("session_attachments") or []),
        }

    def _node_rewrite_queries(self, state: PolicyRagState) -> dict[str, Any]:
        rewritten = build_rewritten_queries_skill(state["query"], state["intent"])
        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "query_rewrite",
                "rewritten_queries": rewritten,
            }
        )
        return {"rewritten_queries": rewritten, "retrieval_trace": trace}

    def _node_retrieve(self, state: PolicyRagState) -> dict[str, Any]:
        queries = unique_queries_skill([state["query"], *state.get("rewritten_queries", [])])
        metadata_filter = state.get("metadata_filter")
        vector_results: list[list[dict[str, Any]]] = []
        for query in queries:
            cache_key = build_cache_key(
                session_id=state.get("session_id"),
                query=query,
                year=state["year"],
                exam_type=state["exam_type"],
                doc_group=state["doc_group"],
                doc_type=state["doc_type"],
            )
            cached = self.session_service.get_cached_response(
                session_id=UUID(state["session_id"]) if state.get("session_id") else None,
                query_hash=cache_key,
            )
            if cached and "vector_results" in cached:
                vector_results.append(list(cached["vector_results"]))
                continue

            query_vector = self.embedding_service.embed_text(query)
            hits = self.milvus_store.search(
                query_vector=query_vector,
                filter_expr=metadata_filter,
                top_k=max(state["top_k"], 8),
            )
            vector_results.append(hits)
            self.session_service.set_cached_response(
                session_id=UUID(state["session_id"]) if state.get("session_id") else None,
                query_hash=cache_key,
                request_json={
                    "query": query,
                    "metadata_filter": metadata_filter,
                    "top_k": state["top_k"],
                },
                response_json={"vector_results": hits},
            )

        bm25_candidates = self.milvus_store.query_documents(
            filter_expr=metadata_filter,
            limit=max(state["top_k"] * 20, 100),
        )
        bm25_results = self.hybrid_retrieval_service.score_documents(
            query=state["query"],
            documents=bm25_candidates,
            top_n=max(state["top_k"], 10),
        )

        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "vector_search",
                "query_count": len(queries),
                "result_counts": [len(result) for result in vector_results],
                "metadata_filter": metadata_filter,
            }
        )
        trace.append(
            {
                "step": "hybrid_retrieval",
                "bm25_candidates": len(bm25_candidates),
                "bm25_results": len(bm25_results),
                "top_ids": [item.get("id") for item in bm25_results[:5]],
            }
        )
        return {
            "vector_results": [*vector_results, bm25_results],
            "retrieval_trace": trace,
        }

    def _node_fuse_and_rerank(self, state: PolicyRagState) -> dict[str, Any]:
        fused = rrf_fusion_skill(state.get("vector_results") or [])
        rerank_results: list[dict[str, Any]] = fused
        if state.get("use_rerank", True) and fused:
            rerank_results = self.rerank_service.rerank(
                query=state["query"],
                documents=fused,
                top_n=min(state["top_k"], 6),
            )

        citations = self._build_citations(rerank_results)
        attachment_citations = self._build_attachment_citations(
            list(state.get("session_attachments") or [])
        )
        citations = [*citations, *attachment_citations]
        historical_reference = any(
            citation.get("year") not in (None, state["year"])
            for citation in citations
            if citation.get("source_kind") != "session_attachment"
        )

        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "rrf_fusion",
                "fused_count": len(fused),
                "top_ids": [item.get("id") for item in fused[: min(5, len(fused))]],
            }
        )
        trace.append(
            {
                "step": "rerank",
                "rerank_count": len(rerank_results),
                "top_scores": [
                    item.get("rerank_score", item.get("score"))
                    for item in rerank_results[:5]
                ],
            }
        )
        if attachment_citations:
            trace.append(
                {
                    "step": "session_attachments",
                    "attachment_count": len(attachment_citations),
                }
            )
        return {
            "fused_results": fused,
            "rerank_results": rerank_results,
            "citations": citations,
            "historical_reference": historical_reference,
            "retrieval_trace": trace,
            "session_attachments": list(state.get("session_attachments") or []),
        }

    def _node_react_evidence_review(
        self,
        state: PolicyRagState,
    ) -> dict[str, Any]:
        citations = list(state.get("citations") or [])
        trace = list(state.get("retrieval_trace") or [])

        if not bool(state.get("need_rag", True)) or len(citations) >= 2:
            trace.append(
                {
                    "step": "react_evidence_review",
                    "action": "skip",
                    "reason": "enough_evidence",
                    "citation_count": len(citations),
                }
            )
            return {
                "retrieval_trace": trace,
                "citations": citations,
                "rerank_results": list(state.get("rerank_results") or []),
                "session_attachments": list(state.get("session_attachments") or []),
            }

        follow_up_query = self._build_follow_up_evidence_query(state)
        extra_hits: list[dict[str, Any]] = []
        try:
            query_vector = self.embedding_service.embed_text(follow_up_query)
            extra_hits = self.milvus_store.search(
                query_vector=query_vector,
                filter_expr=state.get("metadata_filter"),
                top_k=max(state.get("top_k", 6), 4),
            )
            if extra_hits:
                extra_hits = self.rerank_service.rerank(
                    query=follow_up_query,
                    documents=extra_hits,
                    top_n=min(state.get("top_k", 6), 4),
                )
        except Exception:
            extra_hits = []

        extra_citations = self._build_citations(extra_hits)
        merged_citations = self._merge_citations(citations, extra_citations)
        trace.append(
            {
                "step": "react_evidence_review",
                "action": "refine",
                "follow_up_query": follow_up_query,
                "extra_hit_count": len(extra_hits),
                "citation_count": len(merged_citations),
            }
        )
        return {
            "citations": merged_citations,
            "rerank_results": list(extra_hits) if extra_hits else list(state.get("rerank_results") or []),
            "retrieval_trace": trace,
            "session_attachments": list(state.get("session_attachments") or []),
            "historical_reference": any(
                citation.get("year") not in (None, state["year"])
                for citation in merged_citations
                if citation.get("source_kind") != "session_attachment"
            ),
        }

    def _node_answer(self, state: PolicyRagState) -> dict[str, Any]:
        citations = list(state.get("citations") or [])
        trace = list(state.get("retrieval_trace") or [])
        if not citations:
            answer = "当前知识库未找到明确依据。"
            trace.append(
                {
                    "step": "citation_guard",
                    "passed": False,
                    "reason": "no_reliable_citations",
                }
            )
            return {
                "answer": answer,
                "retrieval_trace": trace,
                "session_attachments": list(state.get("session_attachments") or []),
            }

        prompt = self._build_answer_prompt(state, citations)
        answer = self._generate_answer(prompt, citations)
        trace.append(
            {
                "step": "answer_generation",
                "evidence_count": len(citations),
                "used_llm": bool(answer and answer != "当前知识库未找到明确依据。"),
            }
        )
        return {
            "answer": answer,
            "retrieval_trace": trace,
            "session_attachments": list(state.get("session_attachments") or []),
        }

    def _generate_answer(
        self,
        prompt: str,
        citations: list[dict[str, Any]],
    ) -> str:
        """Generate an evidence-grounded answer with a deterministic fallback."""
        try:
            response = self.chat_service.chat_completion(
                [
                    {"role": "system", "content": POLICY_RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            if response and response.strip():
                return self._normalize_answer_text(response)
        except Exception:
            pass

        first = citations[0]
        if first.get("source_kind") == "session_attachment":
            answer = (
                f"根据你上传的附件《{first.get('original_name') or first.get('file_name') or '未命名附件'}》，"
                f"当前可参考的摘要是：{first.get('summary') or first.get('content') or '暂无摘要'}。"
            )
            if len(citations) > 1:
                answer += " 结合其他附件信息，建议继续补充更明确的问题。"
            return self._normalize_answer_text(answer)

        answer = (
            f"根据知识库资料，{first.get('doc_title') or '相关文档'}中关于"
            f"{first.get('section') or '相关章节'}的说明可以作为参考。"
        )
        if len(citations) > 1:
            answer += " 结合多条证据，可以进一步核对对应原文。"
        return self._normalize_answer_text(answer)

    def _build_follow_up_evidence_query(self, state: PolicyRagState) -> str:
        parts = [str(state.get("query") or "").strip(), "瀹樻柟渚濇嵁", "璧勬牸鏉′欢"]
        if state.get("doc_group"):
            parts.append(str(state.get("doc_group")))
        if state.get("doc_type"):
            parts.append(str(state.get("doc_type")))
        return " ".join(part for part in parts if part)

    def _merge_citations(
        self,
        citations: list[dict[str, Any]],
        extra_citations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*citations, *extra_citations]:
            key = str(
                item.get("chunk_id")
                or item.get("source_file")
                or item.get("doc_title")
                or ""
            )
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _build_evidence_block(self, citations: list[dict[str, Any]]) -> str:
        if not citations:
            return "当前知识库未检索到明确证据。"

        blocks: list[str] = []
        for index, item in enumerate(citations[:8], start=1):
            title = (
                item.get("doc_title")
                or item.get("source_file")
                or item.get("original_name")
                or item.get("file_name")
                or "未命名来源"
            )
            section = item.get("section")
            page_start = item.get("page_start")
            page_end = item.get("page_end")
            score = item.get("rerank_score", item.get("score"))
            content = (
                item.get("content_excerpt")
                or item.get("content")
                or item.get("summary")
                or item.get("extracted_text")
                or ""
            )
            content_text = self._excerpt(str(content), limit=900) if content else "无摘要"

            lines = [f"[{index}] {title}"]
            if section:
                lines.append(f"章节：{section}")
            if page_start is not None or page_end is not None:
                lines.append(f"页码：{page_start or '?'}-{page_end or page_start or '?'}")
            if score is not None:
                lines.append(f"相关度：{score}")
            lines.append(f"内容：{content_text}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

    def _build_answer_prompt(
        self,
        state: PolicyRagState,
        citations: list[dict[str, Any]],
    ) -> str:
        evidence = self._build_evidence_block(citations)
        attachment_block = self._build_attachment_block(
            list(state.get("session_attachments") or [])
        )
        if attachment_block:
            evidence = "\n\n".join(
                part for part in (evidence, attachment_block) if part.strip()
            )
        memory = self._build_natural_memory_block(state.get("memory_context"))
        return POLICY_RAG_USER_PROMPT_TEMPLATE.format(
            question=state["query"],
            memory=memory,
            evidence=evidence,
        )

    def _build_direct_answer_prompt(self, state: PolicyRagState) -> str:
        memory = self._build_natural_memory_block(state.get("memory_context"))
        attachment_block = self._build_attachment_block(
            list(state.get("session_attachments") or [])
        )
        if attachment_block:
            memory = "\n\n".join(
                part for part in (memory, attachment_block) if part.strip()
            )
        return DIRECT_ANSWER_USER_PROMPT_TEMPLATE.format(
            question=state["query"],
            memory=memory,
        )

    def _build_natural_memory_block(self, memory_context: dict[str, Any] | None) -> str:
        if not memory_context:
            return "暂无可用记忆。"

        lines: list[str] = [
            "以下记忆仅供参考，遇到冲突时以用户最新明确说明为准。",
        ]
        side_query_memory_text = str(
            memory_context.get("side_query_memory_text") or ""
        ).strip()
        if side_query_memory_text:
            lines.append("按需加载的历史记忆：")
            lines.append(side_query_memory_text)
        session_summary = str(memory_context.get("session_summary") or "").strip()
        if session_summary:
            lines.append(f"会话摘要：{session_summary}")
        active_topic = str(memory_context.get("active_topic") or "").strip()
        if active_topic:
            lines.append(f"当前话题：{active_topic}")
        last_intent = str(memory_context.get("last_intent") or "").strip()
        if last_intent:
            lines.append(f"最近意图：{last_intent}")
        open_topics = memory_context.get("open_topics") or []
        if open_topics:
            lines.append("待跟进话题：" + "、".join(str(item) for item in open_topics[:5]))
        recent_messages = memory_context.get("recent_messages") or []
        if recent_messages:
            recent_lines: list[str] = []
            for item in recent_messages[-4:]:
                role = "用户" if item.get("role") == "user" else "助手"
                content = str(item.get("content") or "").replace("\n", " ").strip()
                if len(content) > 80:
                    content = f"{content[:77]}..."
                recent_lines.append(f"{role}：{content}")
            if recent_lines:
                lines.append("最近对话：" + "；".join(recent_lines))
        long_term_context = memory_context.get("long_term_context") or {}
        if long_term_context:
            summary_parts = self._summarize_long_term_context(long_term_context)
            if summary_parts:
                lines.append("长期记忆：" + "；".join(summary_parts))
        return "\n".join(lines)
    def _build_memory_block(self, memory_context: dict[str, Any] | None) -> str:
        if not memory_context:
            return "无"
        lines: list[str] = [
            "以下记忆仅供参考，遇到冲突时以用户最新明确说明为准；不要把不确定的信息说成定论。",
        ]
        side_query_memory_text = str(
            memory_context.get("side_query_memory_text") or ""
        ).strip()
        if side_query_memory_text:
            lines.append("按需加载的历史记忆：")
            lines.append(side_query_memory_text)
        session_summary = str(memory_context.get("session_summary") or "").strip()
        if session_summary:
            lines.append(f"会话摘要：{session_summary}")
        active_topic = str(memory_context.get("active_topic") or "").strip()
        if active_topic:
            lines.append(f"当前话题：{active_topic}")
        last_intent = str(memory_context.get("last_intent") or "").strip()
        if last_intent:
            lines.append(f"最近意图：{last_intent}")
        mentioned_docs = memory_context.get("mentioned_docs") or []
        if mentioned_docs:
            lines.append("已提及资料：" + "、".join(str(item) for item in mentioned_docs))
        conversation_memory = memory_context.get("conversation_memory") or {}
        if conversation_memory:
            memory_parts = [f"{key}={value}" for key, value in conversation_memory.items() if value]
            if memory_parts:
                lines.append("短期记忆：" + "；".join(memory_parts))
        long_term_context = memory_context.get("long_term_context") or {}
        if long_term_context:
            summary_parts = self._summarize_long_term_context(long_term_context)
            if summary_parts:
                lines.append("长期记忆：" + "；".join(summary_parts))
        return "\n".join(lines) if lines else "无"
    def _summarize_long_term_context(self, long_term_context: dict[str, Any]) -> list[str]:
        parts: list[str] = []
        user_profile = long_term_context.get("user_profile") or {}
        if user_profile:
            profile_parts: list[str] = []
            profile_fields = [
                ("name", "姓名"),
                ("nickname", "昵称"),
                ("major", "专业"),
                ("education", "学历"),
                ("degree", "学位"),
                ("political_status", "政治面貌"),
                ("target_regions", "地区偏好"),
                ("desired_departments", "部门偏好"),
                ("desired_positions", "岗位偏好"),
                ("is_fresh_graduate", "应届"),
                ("grassroots_experience_years", "基层年限"),
            ]
            for key, label in profile_fields:
                value = user_profile.get(key)
                if value in (None, "", [], {}):
                    continue
                profile_parts.append(f"{label}={value}")
            if profile_parts:
                parts.append("用户基础资料=" + "、".join(profile_parts))
        liked_departments = long_term_context.get("liked_departments") or []
        if liked_departments:
            parts.append("喜欢的部门=" + "、".join(str(item) for item in liked_departments[:5]))
        liked_job_titles = long_term_context.get("liked_job_titles") or []
        if liked_job_titles:
            parts.append("喜欢的岗位=" + "、".join(str(item) for item in liked_job_titles[:5]))
        total_analyses = long_term_context.get("total_analyses")
        if total_analyses is not None:
            parts.append(f"历史分析次数={total_analyses}")
        total_decisions = long_term_context.get("total_decisions")
        if total_decisions is not None:
            parts.append(f"历史决策次数={total_decisions}")
        last_analysis_at = str(long_term_context.get("last_analysis_at") or "").strip()
        if last_analysis_at:
            parts.append(f"最近分析时间={last_analysis_at}")
        return parts

    def _normalize_answer_text(self, text: str) -> str:
        cleaned = text.replace("```", "").replace("**", "").replace("__", "")
        lines: list[str] = []
        bullet_prefixes = ("-", "•", "·", "∙", "●", "◦", "▪", "▫", "–", "—", "◆", "◇", "○", "■", "□")
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            line = re.sub(r"^#{1,6}\s*", "", line)
            line = re.sub(r"^\*+\s*", "", line)
            while line and line[0] in bullet_prefixes:
                line = line[1:].lstrip()
            line = line.replace("*", "")
            lines.append(line)
        normalized = "\n".join(lines)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _build_citations(self, rerank_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in rerank_results[: min(len(rerank_results), 6)]:
            item_id = str(item.get("id") or "")
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            citations.append(
                {
                    "chunk_id": item_id,
                    "content": item.get("content", ""),
                    "score": float(item.get("score", 0.0)),
                    "rerank_score": float(
                        item.get("rerank_score", item.get("score", 0.0))
                    ),
                    "metadata": dict(item.get("metadata") or {}),
                    "source_file": item.get("source_file"),
                    "doc_title": item.get("doc_title"),
                    "section": item.get("section"),
                    "page_start": item.get("page_start"),
                    "page_end": item.get("page_end"),
                    "doc_group": item.get("doc_group"),
                    "doc_type": item.get("doc_type"),
                    "year": item.get("year"),
                    "exam_type": item.get("exam_type"),
                    "province": item.get("province"),
                    "content_excerpt": self._excerpt(str(item.get("content", ""))),
                }
            )
        return citations

    def _build_attachment_citations(
        self,
        attachments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for attachment in attachments:
            attachment_id = str(attachment.get("id") or "")
            summary = str(attachment.get("summary") or "")
            extracted_text = str(attachment.get("extracted_text") or "")
            citations.append(
                {
                    "chunk_id": f"attachment:{attachment_id}" if attachment_id else None,
                    "source_kind": "session_attachment",
                    "attachment_id": attachment_id,
                    "file_name": attachment.get("file_name"),
                    "original_name": attachment.get("original_name"),
                    "attachment_type": attachment.get("attachment_type"),
                    "mime_type": attachment.get("mime_type"),
                    "file_path": attachment.get("file_path"),
                    "summary": summary,
                    "extracted_text": extracted_text,
                    "content": summary or extracted_text,
                    "content_excerpt": self._excerpt(summary or extracted_text),
                    "score": 1.0,
                    "rerank_score": 1.0,
                    "metadata": dict(attachment.get("metadata_json") or {}),
                }
            )
        return citations

    def _build_attachment_block(
        self,
        attachments: list[dict[str, Any]],
    ) -> str:
        if not attachments:
            return ""

        blocks: list[str] = []
        for index, attachment in enumerate(attachments, start=1):
            original_name = str(
                attachment.get("original_name") or attachment.get("file_name") or ""
            ).strip()
            attachment_type = str(attachment.get("attachment_type") or "").strip()
            summary = str(attachment.get("summary") or "").strip()
            extracted_text = str(attachment.get("extracted_text") or "").strip()
            excerpt = self._excerpt(extracted_text, limit=600) if extracted_text else ""

            lines = [f"[{index}] 会话附件：{original_name or '未命名附件'}"]
            if attachment_type:
                lines.append(f"类型：{attachment_type}")
            if summary:
                lines.append(f"摘要：{summary}")
            if excerpt:
                lines.append(f"识别文本：{excerpt}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

    def _rrf_fusion(
        self,
        result_lists: list[list[dict[str, Any]]],
        k: int = 60,
    ) -> list[dict[str, Any]]:
        return rrf_fusion_skill(result_lists, k=k)

    def _unique_queries(self, queries: list[str]) -> list[str]:
        return unique_queries_skill(queries)

    def _excerpt(self, text: str, limit: int = 240) -> str:
        text = text.strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3]}..."

    def _build_session_title(self, query: str, result: dict[str, Any]) -> str:
        intent = str(result.get("intent") or "")
        return build_session_title_skill(
            intent=intent,
            query=query,
            excerpt_fn=self._excerpt,
        )

    def _extract_mentioned_docs(self, citations: list[dict[str, Any]]) -> list[str]:
        return unique_citation_docs_skill(citations)

    def _serialize_session(self, session_obj: Any) -> dict[str, Any]:
        return {
            "id": str(session_obj.id),
            "title": session_obj.title,
            "last_intent": session_obj.last_intent,
            "active_topic": session_obj.active_topic,
            "mentioned_docs": list(session_obj.mentioned_docs or []),
            "summary": session_obj.summary,
            "created_at": session_obj.created_at.isoformat()
            if session_obj.created_at
            else None,
        }

    def _serialize_message(self, message_obj: Any) -> dict[str, Any]:
        return {
            "id": str(message_obj.id),
            "session_id": str(message_obj.session_id),
            "role": message_obj.role,
            "content": message_obj.content,
            "intent": message_obj.intent,
            "historical_reference": message_obj.historical_reference,
            "citations": list(message_obj.citations or []),
            "retrieval_trace": list(message_obj.retrieval_trace or []),
            "metadata_json": dict(message_obj.metadata_json or {}),
            "created_at": message_obj.created_at.isoformat()
            if message_obj.created_at
            else None,
        }

    def _build_session_service(self) -> ChatSessionService:
        if self.session is None:
            raise RuntimeError("SQLModel session is required for chat session service.")
        return ChatSessionService(self.session)

    def _load_session_attachments(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> list[dict[str, Any]]:
        attachments = self.session_service.list_attachments(session_id, user_id)
        multimodal_service: MultimodalSummaryService | None = None
        updated = False
        serialized: list[dict[str, Any]] = []
        for attachment in attachments:
            if (
                attachment.attachment_type == "other"
                and Path(attachment.file_path or "").suffix.lower() in {
                    ".txt",
                    ".md",
                    ".markdown",
                    ".csv",
                    ".json",
                    ".log",
                    ".xml",
                    ".html",
                    ".htm",
                }
                and attachment.file_path
            ):
                try:
                    extracted_text = Path(attachment.file_path).read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).strip()
                    attachment.attachment_type = "text"
                    attachment.extracted_text = extracted_text
                    attachment.summary = self._excerpt(extracted_text, limit=800)
                    attachment.extraction_status = "text_extracted"
                    self.session.add(attachment)
                    updated = True
                except Exception:
                    pass
            if (
                attachment.attachment_type == "image"
                and attachment.extraction_status != "success"
                and attachment.file_path
            ):
                if multimodal_service is None:
                    multimodal_service = MultimodalSummaryService()
                result = multimodal_service.summarize_image(
                    image_path=attachment.file_path,
                    source_file=attachment.original_name,
                )
                attachment.summary = str(result.get("summary") or "")
                attachment.extracted_text = str(result.get("ocr_text") or "")
                attachment.extraction_status = str(
                    result.get("extraction_status") or "pending_multimodal_summary"
                )
                self.session.add(attachment)
                updated = True

            serialized.append(
                {
                    "id": str(attachment.id),
                    "file_name": attachment.file_name,
                    "original_name": attachment.original_name,
                    "attachment_type": attachment.attachment_type,
                    "mime_type": attachment.mime_type,
                    "file_path": attachment.file_path,
                    "summary": attachment.summary,
                    "extracted_text": attachment.extracted_text,
                    "extraction_status": attachment.extraction_status,
                    "metadata_json": dict(attachment.metadata_json or {}),
                }
            )
        if updated:
            self.session.commit()
        return serialized
