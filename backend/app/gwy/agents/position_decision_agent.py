from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import or_
from sqlmodel import Session, select

from app.gwy.llm.chat_service import ChatService
from app.gwy.models import (
    GwyPosition,
    GwyRecommendationItem,
    GwyRecommendationTask,
    GwyUserProfile,
)
from app.gwy.skills.position_recommendation_skills import (
    PositionRecommendationCriteria,
    build_position_brief,
    build_recommendation_summary,
    extract_position_recommendation_criteria,
    _major_requirement_search_terms,
    position_passes_hard_filters,
    position_to_dict,
    score_position,
)


logger = logging.getLogger(__name__)


class PositionDecisionState(TypedDict, total=False):
    query: str
    user_id: str | None
    session_id: str | None
    year: int
    exam_type: str
    top_k: int
    persist_result: bool
    profile_override: dict[str, Any] | None
    profile: dict[str, Any] | None
    criteria: PositionRecommendationCriteria
    candidates: list[dict[str, Any]]
    filtered_positions: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    summary: dict[str, Any]
    answer: str
    task_id: str | None
    need_more_info: bool
    missing_fields: list[str]
    retrieval_trace: list[dict[str, Any]]


@dataclass(slots=True)
class PositionDecisionResult:
    task: GwyRecommendationTask | None
    recommendations: list[dict[str, Any]]
    answer: str
    summary: dict[str, Any]
    retrieval_trace: list[dict[str, Any]]
    need_more_info: bool
    missing_fields: list[str]


class PositionDecisionAgent:
    def __init__(
        self,
        *,
        session: Session,
        chat_service: ChatService | None = None,
    ) -> None:
        self.session = session
        self.chat_service = chat_service or ChatService()
        self.graph = self._build_graph()

    def run(
        self,
        *,
        query: str,
        user_id: UUID | None,
        session_id: UUID | None = None,
        year: int = 2026,
        exam_type: str = "national",
        top_k: int = 5,
        persist_result: bool = True,
        profile_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state: PositionDecisionState = {
            "query": query,
            "user_id": str(user_id) if user_id else None,
            "session_id": str(session_id) if session_id else None,
            "year": year,
            "exam_type": exam_type,
            "top_k": top_k,
            "persist_result": persist_result,
            "profile_override": profile_override,
            "retrieval_trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self) -> Any:
        builder = StateGraph(PositionDecisionState)
        builder.add_node("analyze_request", self._node_analyze_request)
        builder.add_node("load_candidates", self._node_load_candidates)
        builder.add_node("filter_and_rank", self._node_filter_and_rank)
        builder.add_node("persist_recommendation", self._node_persist_recommendation)
        builder.add_node("compose_answer", self._node_compose_answer)
        builder.add_edge(START, "analyze_request")
        builder.add_edge("analyze_request", "load_candidates")
        builder.add_edge("load_candidates", "filter_and_rank")
        builder.add_edge("filter_and_rank", "persist_recommendation")
        builder.add_edge("persist_recommendation", "compose_answer")
        builder.add_edge("compose_answer", END)
        return builder.compile()

    def _node_analyze_request(self, state: PositionDecisionState) -> dict[str, Any]:
        if state.get("profile_override"):
            profile = dict(state.get("profile_override") or {})
        else:
            profile = (
                self._load_profile(UUID(state["user_id"]))
                if state.get("user_id")
                else None
            )
        criteria = extract_position_recommendation_criteria(state["query"], profile)
        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "position_intent_analysis",
                "agent": "PositionDecisionAgent",
                "skill": "extract_position_recommendation_criteria",
                "tool": "position_recommendation_parser",
                "missing_fields": list(criteria.missing_fields),
                "strict_region": bool(criteria.strict_region),
                "major": criteria.major,
                "education": criteria.education,
                "degree": criteria.degree,
                "political_status": criteria.political_status,
                "profile_source": "explicit_override" if state.get("profile_override") else "user_profile" if state.get("user_id") else "query",
            }
        )
        return {
            "profile": criteria.profile_summary,
            "criteria": criteria,
            "retrieval_trace": trace,
            "need_more_info": bool(criteria.missing_fields),
            "missing_fields": list(criteria.missing_fields),
        }

    def _node_load_candidates(
        self,
        state: PositionDecisionState,
    ) -> dict[str, Any]:
        criteria = state["criteria"]
        base_statement = select(GwyPosition).order_by(GwyPosition.source_row_number.asc())
        sql_filters = []
        if state.get("year"):
            sql_filters.append(
                or_(
                    GwyPosition.source_file.contains(str(state["year"])),
                    GwyPosition.source_file.contains(f"{state['year']}年度"),
                )
            )

        def _text_clause(
            column: Any,
            value: str | None,
            *,
            extra_terms: list[str] | tuple[str, ...] = (),
        ) -> Any:
            clauses = [column.is_(None), column == ""]
            if value:
                clauses.append(column.contains(value))
            for term in extra_terms:
                if term and term != value:
                    clauses.append(column.contains(term))
            clauses.extend([column.contains("不限"), column.contains("不限制")])
            return or_(*clauses)

        if criteria.major:
            major_terms = _major_requirement_search_terms(criteria.major)
            sql_filters.append(
                _text_clause(
                    GwyPosition.major_requirement,
                    criteria.major,
                    extra_terms=major_terms,
                )
            )
        if criteria.education:
            sql_filters.append(
                _text_clause(GwyPosition.education_requirement, criteria.education)
            )
        if criteria.degree:
            sql_filters.append(
                _text_clause(
                    GwyPosition.degree_requirement,
                    criteria.degree,
                    extra_terms=("相对应", "最高学历", "对应学位"),
                )
            )
        if criteria.political_status:
            sql_filters.append(
                _text_clause(
                    GwyPosition.political_status_requirement,
                    criteria.political_status,
                )
            )
        if criteria.strict_region and criteria.target_regions:
            region_clauses = []
            for region in criteria.target_regions:
                region_clauses.extend(
                    [
                        GwyPosition.work_location.contains(region),
                        GwyPosition.household_registration_location.contains(region),
                        GwyPosition.position_distribution.contains(region),
                    ]
                )
            if region_clauses:
                sql_filters.append(or_(*region_clauses))
        if criteria.desired_departments:
            department_clauses = []
            for name in criteria.desired_departments:
                department_clauses.extend(
                    [
                        GwyPosition.department_name.contains(name),
                        GwyPosition.office_name.contains(name),
                    ]
                )
            if department_clauses:
                sql_filters.append(or_(*department_clauses))
        if criteria.desired_positions:
            position_clauses = []
            for name in criteria.desired_positions:
                position_clauses.extend(
                    [
                        GwyPosition.job_title.contains(name),
                        GwyPosition.position_desc.contains(name),
                    ]
                )
            if position_clauses:
                sql_filters.append(or_(*position_clauses))

        filtered_statement = (
            base_statement.where(*sql_filters) if sql_filters else base_statement
        )
        self._log_position_sql(
            filtered_statement,
            criteria=criteria,
            state=state,
            sql_filter_count=len(sql_filters),
            stage="position_candidate_load",
        )
        filtered_rows = self.session.exec(filtered_statement).all()
        used_sql_filter = bool(sql_filters)
        year_fallback_used = False
        if filtered_rows:
            candidates = [position_to_dict(item) for item in filtered_rows]
        else:
            explicit_mode = str(state.get("mode") or "") == "position_recommendation"
            if explicit_mode:
                logger.info(
                    "Gwy position SQL no-fallback for explicit mode | year=%s exam_type=%s query=%s",
                    state.get("year"),
                    state.get("exam_type"),
                    state.get("query"),
                )
                candidates = []
                used_sql_filter = bool(sql_filters)
            else:
                year_fallback_used = bool(state.get("year")) and bool(sql_filters)
                if year_fallback_used:
                    logger.info(
                        "Gwy position SQL fallback to unfiltered query | year=%s exam_type=%s query=%s",
                        state.get("year"),
                        state.get("exam_type"),
                        state.get("query"),
                    )
                fallback_rows = self.session.exec(base_statement).all()
                candidates = [position_to_dict(item) for item in fallback_rows]
                used_sql_filter = bool(sql_filters) and bool(candidates)
        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "position_candidate_load",
                "agent": "PositionDecisionAgent",
                "tool": "PostgreSQL",
                "backend": "sqlmodel_session.exec",
                "candidate_count": len(candidates),
                "sql_filtered": used_sql_filter,
                "sql_filter_count": len(sql_filters),
                "year_filter_fallback": year_fallback_used,
                "year": state.get("year"),
                "exam_type": state.get("exam_type"),
                "major_search_terms": _major_requirement_search_terms(criteria.major)
                if criteria.major
                else [],
            }
        )
        if criteria.target_regions:
            trace[-1]["target_regions"] = list(criteria.target_regions)
        return {
            "candidates": candidates,
            "retrieval_trace": trace,
        }

    def _node_filter_and_rank(
        self,
        state: PositionDecisionState,
    ) -> dict[str, Any]:
        criteria = state["criteria"]
        candidates = list(state.get("candidates") or [])
        exact_matches: list[dict[str, Any]] = []
        relaxed_matches: list[dict[str, Any]] = []

        for candidate in candidates:
            matched, hard_reasons, hard_risks = position_passes_hard_filters(
                candidate,
                criteria,
            )
            scored = score_position(candidate, criteria)
            record = {
                **candidate,
                **scored,
                "hard_filter_passed": matched,
                "hard_filter_reasons": hard_reasons,
                "hard_filter_risks": hard_risks,
            }
            if matched:
                exact_matches.append(record)
            else:
                relaxed_matches.append(record)

        ranked_source = exact_matches if exact_matches else relaxed_matches
        ranked_source.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        recommendations = [
            build_position_brief(item, {
                "score": item.get("score", 0.0),
                "recommend_level": item.get("recommend_level", "weak_match"),
                "risk_level": item.get("risk_level", "high"),
                "need_manual_confirm": item.get("need_manual_confirm", True),
                "reasons": list(item.get("reasons") or []),
                "risks": list(item.get("risks") or []),
            })
            for item in ranked_source[: state["top_k"]]
        ]
        need_more_info = bool(state.get("need_more_info"))
        summary = build_recommendation_summary(
            criteria,
            recommendations,
            candidate_count=len(candidates),
            filtered_count=len(exact_matches),
        )
        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "position_filter_and_rank",
                "agent": "PositionDecisionAgent",
                "skill": "position_passes_hard_filters / score_position",
                "candidate_count": len(candidates),
                "exact_match_count": len(exact_matches),
                "relaxed_match_count": len(relaxed_matches),
                "selected_count": len(recommendations),
                "need_more_info": need_more_info,
            }
        )
        return {
            "filtered_positions": exact_matches,
            "recommendations": recommendations,
            "summary": summary,
            "need_more_info": need_more_info,
            "missing_fields": list(criteria.missing_fields),
            "retrieval_trace": trace,
        }

    def _node_persist_recommendation(
        self,
        state: PositionDecisionState,
    ) -> dict[str, Any]:
        if not bool(state.get("persist_result", True)):
            trace = list(state.get("retrieval_trace") or [])
            trace.append(
                {
                    "step": "position_persist",
                    "agent": "PositionDecisionAgent",
                    "tool": "GwyRecommendationTask",
                    "backend": "sqlmodel_session.commit",
                    "task_id": None,
                    "item_count": len(state.get("recommendations") or []),
                    "status": "skipped",
                    "reason": "persist_disabled",
                }
            )
            return {"task_id": None, "retrieval_trace": trace}

        task = GwyRecommendationTask(
            user_id=UUID(state["user_id"]) if state.get("user_id") else None,
            exam_year=state.get("year"),
            exam_type=state.get("exam_type"),
            target_regions=list(
                state.get("criteria").target_regions if state.get("criteria") else []
            ),
            top_k=state.get("top_k", 5),
            status="completed",
            summary=dict(state.get("summary") or {}),
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)

        for rank, item in enumerate(state.get("recommendations") or [], start=1):
            self.session.add(
                GwyRecommendationItem(
                    task_id=task.id,
                    position_id=UUID(item["position_id"]),
                    rank=rank,
                    score=float(item.get("score", 0.0)),
                    recommend_level=str(item.get("recommend_level") or ""),
                    risk_level=str(item.get("risk_level") or ""),
                    need_manual_confirm=bool(item.get("need_manual_confirm", False)),
                    reasons=list(item.get("reasons") or []),
                    risks=list(item.get("risks") or []),
                    citations=[],
                )
            )
        self.session.commit()

        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "position_persist",
                "agent": "PositionDecisionAgent",
                "tool": "GwyRecommendationTask",
                "backend": "sqlmodel_session.commit",
                "task_id": str(task.id),
                "item_count": len(state.get("recommendations") or []),
            }
        )
        return {"task_id": str(task.id), "retrieval_trace": trace}

    def _node_compose_answer(
        self,
        state: PositionDecisionState,
    ) -> dict[str, Any]:
        recommendations = list(state.get("recommendations") or [])
        summary = dict(state.get("summary") or {})
        answer = self._compose_position_answer(state, summary, recommendations)
        trace = list(state.get("retrieval_trace") or [])
        trace.append(
            {
                "step": "position_answer_generation",
                "agent": "PositionDecisionAgent",
                "skill": "build_position_brief / build_recommendation_summary",
                "used_llm": False,
                "recommendation_count": len(recommendations),
            }
        )
        return {
            "answer": answer,
            "retrieval_trace": trace,
            "recommendations": recommendations,
            "summary": summary,
            "need_more_info": bool(state.get("need_more_info", False)),
            "missing_fields": list(state.get("missing_fields") or []),
        }

    def _compose_position_answer(
        self,
        state: PositionDecisionState,
        summary: dict[str, Any],
        recommendations: list[dict[str, Any]],
    ) -> str:
        missing_fields = list(summary.get("missing_fields") or [])
        if missing_fields:
            ask_parts = []
            if missing_fields:
                ask_parts.append("、".join(self._map_missing_fields_to_chinese(missing_fields)))
            else:
                ask_parts.append("专业、学历、学位、地区偏好")
            ask_parts.append("这些信息补齐后，我就能直接按 PostgreSQL 职位表给你筛出具体岗位")
            return "我先不做泛化初筛了。要继续精确推荐岗位，请补充：" + "，".join(ask_parts) + "。"

        if not recommendations:
            return (
                "我已经按 PostgreSQL 职位表做了精确筛选，但暂时没有找到足够合适的岗位。"
                "你可以再补充想去的地区、部门偏好，或者是否接受基层/应届限制，我再继续缩小范围。"
            )

        lines = []
        if summary.get("filtered_count", 0) == 0:
            lines.append(
                "我已经从 PostgreSQL 职位表里筛出当前最接近的岗位。下面这些是优先考虑的选项："
            )
        else:
            lines.append("我已经从 PostgreSQL 职位表里筛出这些匹配岗位：")

        for index, item in enumerate(recommendations[:5], start=1):
            lines.append(
                f"{index}. {item.get('department_name') or '未知部门'}"
                f"{(' / ' + item.get('office_name')) if item.get('office_name') else ''}"
                f"{(' / ' + item.get('job_title')) if item.get('job_title') else ''}"
                f"（代码：{item.get('position_code') or '未知'}，地区：{item.get('work_location') or item.get('position_distribution') or '未知'}，"
                f"学历：{item.get('education_requirement') or '未知'}，学位：{item.get('degree_requirement') or '未知'}）"
            )
            reasons = [
                str(reason.get("text") or "")
                for reason in item.get("reasons") or []
                if reason.get("text")
            ]
            if reasons:
                lines.append("   匹配原因：" + "；".join(reasons[:3]))
            risks = [
                str(risk.get("text") or "")
                for risk in item.get("risks") or []
                if risk.get("text")
            ]
            if risks:
                lines.append("   需要核实：" + "；".join(risks[:2]))

        if summary.get("missing_fields"):
            lines.append(
                "如果你愿意，我还可以继续按这些条件再缩小范围："
                + "、".join(self._map_missing_fields_to_chinese(summary["missing_fields"]))
            )
        return "\n".join(lines)

    def _map_missing_fields_to_chinese(self, fields: list[str]) -> list[str]:
        mapping = {
            "major": "专业",
            "education": "学历",
            "degree": "学位",
            "political_status": "政治面貌",
            "target_regions": "地区偏好",
            "desired_departments": "部门偏好",
            "desired_positions": "岗位偏好",
            "grassroots_experience_years": "基层经历",
        }
        return [mapping.get(field, field) for field in fields]

    def _load_profile(self, user_id: UUID) -> GwyUserProfile | None:
        statement = select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        return self.session.exec(statement).first()

    def _log_position_sql(
        self,
        statement: Any,
        *,
        criteria: PositionRecommendationCriteria,
        state: PositionDecisionState,
        sql_filter_count: int,
        stage: str,
    ) -> None:
        try:
            compiled_sql = str(
                statement.compile(
                    dialect=self.session.get_bind().dialect,
                    compile_kwargs={"literal_binds": True},
                )
            )
        except Exception:  # pragma: no cover - best effort logging only
            compiled_sql = "<failed to render SQL>"

        logger.info(
            "Gwy position SQL | stage=%s year=%s exam_type=%s filters=%s major=%s education=%s degree=%s political_status=%s regions=%s departments=%s positions=%s strict_region=%s query=%s",
            stage,
            state.get("year"),
            state.get("exam_type"),
            sql_filter_count,
            criteria.major,
            criteria.education,
            criteria.degree,
            criteria.political_status,
            list(criteria.target_regions),
            list(criteria.desired_departments),
            list(criteria.desired_positions),
            bool(criteria.strict_region),
            state.get("query"),
        )
        logger.info("Gwy position SQL statement: %s", compiled_sql)

    def _normalize_answer_text(self, text: str) -> str:
        cleaned = text.replace("*", "").replace("```", "")
        return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()
