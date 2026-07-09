from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.gwy.agent_runtime import AgentRuntime, ToolContext, ToolRegistry, ToolSpec
from app.gwy.agent_runtime.builtin_tools import register_builtin_tools
from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
from app.gwy.agents.risk_review_agent import RiskReviewAgent
from app.gwy.llm.chat_service import ChatService
from app.gwy.services.position_catalog_service import PositionCatalogService
from app.gwy.services.study_plan_service import StudyPlanService


POSITION_SNAPSHOT_SYSTEM_PROMPT = """
你是 GwyPilot 的快照岗位推荐分析 Agent，工作方式接近 learn-claude-code 的 AgentRuntime。

工作规则：
- 非简单分析必须先调用 `todo_write`，列出 2-5 步岗位分析计划。
- 必须先围绕固定快照分析，不要脱离快照另做一套岗位推荐。
- 岗位筛选和岗位事实以 PostgreSQL 结构化岗位表为准，不要用 RAG 替代岗位过滤。
- 政策、资格限制和考试规则需要证据支撑；证据不足时必须写“未知”或“无法确认”。
- 最终只输出面向用户的中文 Markdown 报告，不要暴露内部 JSON。
""".strip()


class PositionSnapshotRuntimeService:
    def __init__(
        self,
        *,
        session: Session | None,
        runtime_factory: Callable[..., Any] | None = None,
        position_catalog_service: Any | None = None,
        risk_review_agent: Any | None = None,
        study_plan_service_factory: Callable[[Session | None], Any] | None = None,
        report_generator_agent: Any | None = None,
        chat_service: Any | None = None,
    ) -> None:
        self.session = session
        self.runtime_factory = runtime_factory
        self.chat_service = chat_service
        self.position_catalog_service = position_catalog_service or (
            PositionCatalogService(session) if session is not None else None
        )
        self.risk_review_agent = risk_review_agent or RiskReviewAgent()
        self.study_plan_service_factory = (
            study_plan_service_factory
            or (lambda current_session: StudyPlanService(session=current_session))
        )
        self.report_generator_agent = report_generator_agent or ReportGeneratorAgent(
            chat_service=chat_service,
        )

    def run(
        self,
        *,
        snapshot: dict[str, Any],
        user_id: UUID | str,
        task_id: UUID | str | None = None,
        user_profile: dict[str, Any] | None = None,
        recommendation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = {
            "snapshot": dict(snapshot or {}),
            "query": self._build_query(snapshot=snapshot, user_profile=user_profile or {}),
            "user_id": str(user_id),
            "task_id": str(task_id) if task_id else None,
            "user_profile": dict(user_profile or {}),
            "recommendation_context": dict(recommendation_context or {}),
            "year": self._extract_year(snapshot, recommendation_context),
            "exam_type": self._extract_exam_type(snapshot, recommendation_context),
        }
        runtime = self._build_runtime()
        runtime_result = runtime.run(
            user_prompt=self._build_user_prompt(context),
            context=context,
        )
        return self._serialize_runtime_result(runtime_result)

    def _build_runtime(self) -> Any:
        if self.runtime_factory is not None:
            return self.runtime_factory(
                tools=self._build_tool_registry(),
                system_prompt=POSITION_SNAPSHOT_SYSTEM_PROMPT,
            )
        chat_service = self.chat_service or ChatService()
        return AgentRuntime(
            chat_service=chat_service,
            tools=self._build_tool_registry(),
            system_prompt=POSITION_SNAPSHOT_SYSTEM_PROMPT,
            max_turns=12,
            temperature=0.2,
        )

    def _build_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_builtin_tools(registry)
        registry.register(
            ToolSpec(
                name="load_snapshot",
                description="加载固定岗位快照并写入 runtime state。",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_load_snapshot,
            )
        )
        registry.register(
            ToolSpec(
                name="analyze_snapshot_positions",
                description="基于 PostgreSQL 岗位表分析快照中的岗位。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                handler=self._tool_analyze_snapshot_positions,
            )
        )
        registry.register(
            ToolSpec(
                name="review_position_risks",
                description="复核当前推荐岗位的资格和政策风险。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                handler=self._tool_review_position_risks,
            )
        )
        registry.register(
            ToolSpec(
                name="generate_study_plan",
                description="根据用户画像和推荐岗位生成复习计划。",
                parameters={
                    "type": "object",
                    "properties": {"study_hours_per_day": {"type": "integer"}},
                },
                handler=self._tool_generate_study_plan,
            )
        )
        registry.register(
            ToolSpec(
                name="compose_snapshot_report",
                description="基于快照事实、风险复核和复习计划生成最终 Markdown 报告。",
                parameters={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
                handler=self._tool_compose_snapshot_report,
            )
        )
        return registry

    def _tool_load_snapshot(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        snapshot = dict(context.state.get("snapshot") or {})
        summary = {
            "title": snapshot.get("title"),
            "selected_position_ids": list(snapshot.get("selected_position_ids") or []),
            "visible_columns": list(snapshot.get("visible_columns") or []),
            "filters_json": dict(snapshot.get("filters_json") or {}),
            "notes": snapshot.get("notes") or "",
            "source_sheet": snapshot.get("source_sheet") or "",
        }
        context.state["snapshot_summary"] = summary
        return summary

    def _tool_analyze_snapshot_positions(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        snapshot = dict(context.state.get("snapshot") or {})
        selected_ids = self._parse_uuid_list(snapshot.get("selected_position_ids") or [])
        query = str(args.get("query") or context.state.get("query") or snapshot.get("title") or "")
        profile = dict(context.state.get("user_profile") or {})
        top_k = max(1, len(selected_ids) or int(context.state.get("top_k") or 5))

        if self.position_catalog_service is None:
            result = {
                "summary": {"recommendation_count": 0},
                "recommendations": [],
                "selected_positions": [],
                "retrieval_trace": [],
            }
        else:
            result = self.position_catalog_service.analyze_positions(
                position_ids=selected_ids,
                query=query,
                profile=profile,
                top_k=top_k,
            )

        context.state["position_facts"] = dict(result)
        context.state["recommendations"] = list(result.get("recommendations") or [])
        context.state["selected_positions"] = list(result.get("selected_positions") or [])
        return dict(result)

    def _tool_review_position_risks(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        result = self.risk_review_agent.run(
            query=str(args.get("query") or context.state.get("query") or ""),
            recommendations=list(context.state.get("recommendations") or []),
        )
        context.state["risk_review"] = dict(result)
        return dict(result)

    def _tool_generate_study_plan(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        profile = dict(context.state.get("user_profile") or {})
        try:
            hours = int(args.get("study_hours_per_day") or profile.get("daily_study_hours") or 4)
        except (TypeError, ValueError):
            hours = 4
        service = self.study_plan_service_factory(self.session)
        result = service.generate(
            user_id=UUID(str(context.state["user_id"])),
            user_profile=profile,
            recommendations=list(context.state.get("recommendations") or []),
            task_id=self._optional_uuid(context.state.get("task_id")),
            exam_type=str(context.state.get("exam_type") or "national"),
            exam_year=self._optional_int(context.state.get("year")),
            study_hours_per_day=max(1, hours),
            push_to_feishu=False,
        )
        context.state["study_plan"] = dict(result)
        context.state["study_plan_markdown"] = str(result.get("markdown") or "")
        return dict(result)

    def _tool_compose_snapshot_report(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        title = str(
            args.get("title")
            or (context.state.get("snapshot_summary") or {}).get("title")
            or "岗位推荐分析报告"
        )
        result = self.report_generator_agent.run(
            title=title,
            recommendations=list(context.state.get("recommendations") or []),
            risk_review=dict(context.state.get("risk_review") or {}),
        )
        report = str(result.get("report") or "")
        study_markdown = str(context.state.get("study_plan_markdown") or "")
        if study_markdown and study_markdown not in report:
            report = f"{report.rstrip()}\n\n## 复习计划\n\n{study_markdown}".strip()
        context.state["report"] = report
        context.state["report_meta"] = dict(result.get("report_meta") or {})
        return {"report": report, "report_meta": context.state["report_meta"]}

    def _serialize_runtime_result(self, result: Any) -> dict[str, Any]:
        state = dict(getattr(result, "state", {}) or {})
        report = str(state.get("report") or getattr(result, "answer", "") or "")
        trace = list(getattr(result, "trace", []) or [])
        status = "needs_more_info" if bool(state.get("needs_more_info", False)) else "completed"
        return {
            "status": status,
            "stage": "position_snapshot_runtime",
            "report": report,
            "trace": trace,
            "output_json": {
                "runtime_state": state,
                "agent_journey": trace,
                "trace_count": len(trace),
                "recommendations": list(state.get("recommendations") or []),
                "risk_review": dict(state.get("risk_review") or {}),
                "study_plan": dict(state.get("study_plan") or {}),
            },
            "recommendations": list(state.get("recommendations") or []),
            "risk_review": dict(state.get("risk_review") or {}),
            "study_plan": dict(state.get("study_plan") or {}),
            "needs_more_info": bool(state.get("needs_more_info", False)),
            "missing_fields": list(state.get("missing_fields") or []),
            "clarifying_questions": list(state.get("clarifying_questions") or []),
        }

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        snapshot = dict(context.get("snapshot") or {})
        return (
            f"请基于固定岗位快照「{snapshot.get('title') or '岗位快照'}」生成岗位分析报告。"
            "先制定分析计划，再调用工具核查岗位事实、风险和复习计划，最后输出中文 Markdown。"
        )

    def _build_query(
        self,
        *,
        snapshot: dict[str, Any],
        user_profile: dict[str, Any],
    ) -> str:
        parts = [
            str(snapshot.get("title") or "").strip(),
            str(snapshot.get("notes") or "").strip(),
            str(user_profile.get("major") or "").strip(),
            str(user_profile.get("education") or "").strip(),
            " ".join(list(user_profile.get("target_regions") or [])),
        ]
        return " ".join(part for part in parts if part).strip() or "岗位快照分析"

    def _extract_year(
        self,
        snapshot: dict[str, Any],
        recommendation_context: dict[str, Any] | None,
    ) -> int:
        filters = dict((snapshot or {}).get("filters_json") or {})
        for candidate in (
            (recommendation_context or {}).get("year"),
            filters.get("year"),
        ):
            parsed = self._optional_int(candidate)
            if parsed is not None:
                return parsed
        return 2026

    def _extract_exam_type(
        self,
        snapshot: dict[str, Any],
        recommendation_context: dict[str, Any] | None,
    ) -> str:
        filters = dict((snapshot or {}).get("filters_json") or {})
        return str(
            (recommendation_context or {}).get("exam_type")
            or filters.get("exam_type")
            or "national"
        )

    def _parse_uuid_list(self, values: Any) -> list[UUID]:
        parsed: list[UUID] = []
        for value in list(values or []):
            try:
                parsed.append(UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return parsed

    def _optional_uuid(self, value: Any) -> UUID | None:
        if value in (None, ""):
            return None
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    def _optional_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
