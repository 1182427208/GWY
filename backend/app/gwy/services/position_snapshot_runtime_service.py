from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.gwy.agent_runtime import AgentRuntime, ToolContext, ToolRegistry, ToolSpec
from app.gwy.agent_runtime.builtin_tools import register_builtin_tools
from app.gwy.agents.policy_evidence_agent import PolicyEvidenceAgent
from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
from app.gwy.agents.risk_review_agent import RiskReviewAgent
from app.gwy.llm.chat_service import ChatService
from app.gwy.services.position_catalog_service import PositionCatalogService
from app.gwy.services.position_decision_matrix_service import (
    PositionDecisionMatrixService,
)
from app.gwy.services.report_quality_service import ReportQualityService
from app.gwy.services.study_plan_service import StudyPlanService

POSITION_SNAPSHOT_SYSTEM_PROMPT = """
你是 GwyPilot 的快照岗位推荐分析 Agent，工作方式接近 learn-claude-code 的 AgentRuntime。

工作规则：
- 非简单分析必须先调用 `todo_tasks`（兼容 `todo_write`），列出 2-5 步岗位分析计划。
- 必须先围绕固定快照分析，不要脱离快照另做一套岗位推荐。
- 岗位筛选和岗位事实以 PostgreSQL 结构化岗位表为准，不要用 RAG 替代岗位过滤。
- 政策、资格限制和考试规则需要证据支撑；证据不足时必须写“未知”或“无法确认”。
- 必须先调用 `load_skill` 加载 `position-planning`，再用 `todo_tasks`（兼容 `todo_write`）列出 2-5 步计划。
- `analyze_snapshot_positions` 后，检查工具返回的 `missing`；有历史、政策或隐性条件缺口时，继续调用对应研究工具。
- 报告前必须调用 `build_position_decision_matrix` 和 `validate_report_requirements`，不能只把候选岗位和风险列表交给报告工具。
- 必须进行岗位横向比较并划分冲刺、主攻、保底、谨慎、排除；数据不足时保留未知，不得编造竞争数据。
- 最终只输出面向用户的中文 Markdown 报告，不要暴露内部 JSON。
""".strip()


MCP_TOOL_PRIORITY_PROMPT = """

MCP 工具优先级：
- 公共网页证据核验时，优先用统一 Web MCP：`web_search` -> `web_fetch` / `browser_retrieve` -> `verify_web_evidence`。
- 数据库结构和数据核验时，优先用 DB MCP：`list_tables` -> `describe_table` / `sample_rows` -> `query_sql`。
- 只有当 MCP 无法满足时，才回退到本地推理或已有业务工具。
- 不要跳过工具直接编造证据、表结构、行数据或查询结果。
""".strip()

POSITION_SNAPSHOT_SYSTEM_PROMPT += MCP_TOOL_PRIORITY_PROMPT


class PositionSnapshotRuntimeService:
    def __init__(
        self,
        *,
        session: Session | None,
        runtime_factory: Callable[..., Any] | None = None,
        position_catalog_service: Any | None = None,
        risk_review_agent: Any | None = None,
        policy_evidence_agent: Any | None = None,
        decision_matrix_service: Any | None = None,
        report_quality_service: Any | None = None,
        study_plan_service_factory: Callable[[Session | None], Any] | None = None,
        report_generator_agent: Any | None = None,
        chat_service: Any | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.session = session
        self.runtime_factory = runtime_factory
        self.chat_service = chat_service
        self.position_catalog_service = position_catalog_service or (
            PositionCatalogService(session) if session is not None else None
        )
        self.risk_review_agent = risk_review_agent or RiskReviewAgent()
        self.policy_evidence_agent = policy_evidence_agent
        self.decision_matrix_service = decision_matrix_service or PositionDecisionMatrixService()
        self.report_quality_service = report_quality_service or ReportQualityService()
        self.study_plan_service_factory = (
            study_plan_service_factory
            or (lambda current_session: StudyPlanService(session=current_session))
        )
        self.report_generator_agent = report_generator_agent or ReportGeneratorAgent(
            chat_service=chat_service,
        )
        self.on_event = on_event

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
            on_event=self.on_event,
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
                name="research_position_history",
                description="查询岗位历史招录、进面和竞争趋势；缺失数据必须明确返回缺口。",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_research_position_history,
            )
        )
        registry.register(
            ToolSpec(
                name="retrieve_position_policy_evidence",
                description="使用政策 RAG 检索资格条件、专业目录和考试规则证据。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                handler=self._tool_retrieve_position_policy_evidence,
            )
        )
        registry.register(
            ToolSpec(
                name="verify_position_hidden_requirements",
                description="提取基层、专业测试、户籍、证书、值班出差等隐性条件并生成核验任务。",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_verify_position_hidden_requirements,
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
                name="build_position_decision_matrix",
                description="根据岗位事实、研究结果和风险生成冲刺/主攻/保底/谨慎/排除决策矩阵。",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_build_position_decision_matrix,
            )
        )
        registry.register(
            ToolSpec(
                name="validate_report_requirements",
                description="检查报告是否有结论、分层、横向比较、证据置信度和具体核验动作。",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_validate_report_requirements,
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
        missing = [] if result.get("recommendations") else ["岗位筛选结果"]
        normalized = self._tool_contract(
            status="complete" if not missing else "partial",
            covered=["硬条件", "结构化岗位匹配"],
            missing=missing,
            confidence="high" if not missing else "low",
            next_actions=["研究岗位历史和竞争趋势", "核验政策与隐性条件"],
            data=dict(result),
        )
        context.state["evidence_inventory"] = {
            **dict(context.state.get("evidence_inventory") or {}),
            "covered": normalized["covered"],
            "missing": normalized["missing"],
        }
        return normalized

    def _tool_research_position_history(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del args
        positions = list(context.state.get("selected_positions") or [])
        if not positions or self.position_catalog_service is None:
            return self._tool_contract(
                status="partial",
                covered=[],
                missing=["岗位历史招录和竞争数据"],
                confidence="unknown",
                next_actions=["补充岗位代码或连接岗位历史数据源"],
                data={"items": []},
            )

        items: list[dict[str, Any]] = []
        for position in positions[:10]:
            history = self.position_catalog_service.get_position_history(position, limit=5)
            items.append(
                {
                    "position_id": position.get("id") or position.get("position_id"),
                    "label": self._position_label(position),
                    "history": history,
                }
            )
        context.state["position_research"] = items
        missing = [
            "competition"
            for item in items
            if not (dict(item.get("history") or {}).get("summary") or {}).get(
                "latest_interview_ratio"
            )
        ]
        return self._tool_contract(
            status="complete" if not missing else "partial",
            covered=["历史招录人数", "历史记录"],
            missing=list(dict.fromkeys(missing)),
            confidence="medium" if not missing else "low",
            next_actions=["检索官方公告补充竞争数据"] if missing else [],
            data={"items": items},
        )

    def _tool_retrieve_position_policy_evidence(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        query = str(args.get("query") or context.state.get("query") or "").strip()
        agent = self.policy_evidence_agent
        if agent is None:
            try:
                agent = PolicyEvidenceAgent()
            except Exception:
                agent = None
        if agent is None:
            result = {"policy_evidence": [], "trace": []}
        else:
            try:
                result = agent.run(
                    analysis_scope={
                        "query": query,
                        "report_title": (context.state.get("snapshot_summary") or {}).get("title"),
                        "evidence_queries": [query] if query else [],
                    }
                )
            except Exception:
                result = {"policy_evidence": [], "trace": []}
        evidence = list(result.get("policy_evidence") or [])
        context.state["policy_evidence"] = evidence
        missing = [] if evidence else ["政策和资格条件证据"]
        return self._tool_contract(
            status="complete" if evidence else "partial",
            covered=["政策证据"] if evidence else [],
            missing=missing,
            confidence="medium" if evidence else "unknown",
            next_actions=["以官方公告原文核验关键资格条件"] if not evidence else [],
            data={"policy_evidence": evidence, "trace": list(result.get("trace") or [])},
        )

    def _tool_verify_position_hidden_requirements(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del args
        tasks: list[dict[str, Any]] = []
        for position in list(context.state.get("recommendations") or []):
            remarks = str(position.get("remarks") or "")
            for risk_type, tokens, task in (
                ("service_year_limit", ("基层", "服务年限"), "核对基层经历年限和证明材料"),
                ("professional_test", ("专业测试", "专业考试"), "确认是否参加专业测试及考试科目"),
                ("household_limit", ("户籍", "生源"), "核对户籍、生源或落户限制"),
                ("certificate_limit", ("证书", "资格"), "确认资格证书名称、取得时间和提交材料"),
                ("shift_limit", ("值班", "加班", "出差"), "确认值班、加班和出差频率"),
            ):
                if any(token in remarks for token in tokens):
                    tasks.append(
                        {
                            "position_id": position.get("position_id"),
                            "risk_type": risk_type,
                            "task": task,
                            "source": remarks,
                        }
                    )
        context.state["hidden_requirement_review"] = tasks
        return self._tool_contract(
            status="complete",
            covered=["隐性条件"],
            missing=[] if tasks else ["岗位备注中的隐性条件"],
            confidence="medium" if tasks else "low",
            next_actions=[item["task"] for item in tasks[:6]],
            data={"items": tasks},
        )

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
        risk_items = list(result.get("risk_items") or [])
        return self._tool_contract(
            status="complete",
            covered=["资格和政策风险"],
            missing=[] if risk_items else ["岗位风险证据"],
            confidence="medium" if risk_items else "low",
            next_actions=[
                str(item.get("verification_task") or item.get("suggestion") or "核对官方公告")
                for item in risk_items[:6]
            ],
            data=dict(result),
        )

    def _tool_build_position_decision_matrix(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del args
        result = self.decision_matrix_service.build(
            recommendations=list(context.state.get("recommendations") or []),
            research=list(context.state.get("position_research") or []),
            risk_review=dict(context.state.get("risk_review") or {}),
            profile=dict(context.state.get("user_profile") or {}),
        )
        context.state["decision_matrix"] = result
        context.state["evidence_inventory"] = {
            **dict(context.state.get("evidence_inventory") or {}),
            "missing": list(result.get("missing") or []),
            "confidence": result.get("confidence"),
        }
        return self._tool_contract(
            status="complete" if result.get("items") else "partial",
            covered=["岗位横向比较", "岗位决策分层"],
            missing=list(result.get("missing") or []),
            confidence=str(result.get("confidence") or "unknown"),
            next_actions=list(result.get("next_actions") or []),
            data=result,
        )

    def _tool_validate_report_requirements(
        self,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del args
        result = self.report_quality_service.validate(
            report=str(context.state.get("report") or ""),
            decision_matrix=dict(context.state.get("decision_matrix") or {}),
            risk_review=dict(context.state.get("risk_review") or {}),
        )
        context.state["report_validation"] = result
        return self._tool_contract(
            status="complete" if result.get("passed") else "partial",
            covered=["报告质量校验"] if result.get("passed") else [],
            missing=list(result.get("missing_requirements") or []),
            confidence="high" if result.get("passed") else "low",
            next_actions=list(result.get("next_actions") or []),
            data=result,
        )

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
            decision_matrix=dict(context.state.get("decision_matrix") or {}),
            evidence_inventory=dict(context.state.get("evidence_inventory") or {}),
            verification_tasks=[
                    *(
                        dict(context.state.get("decision_matrix") or {}).get(
                            "next_actions"
                        )
                        or []
                    ),
                    *[
                        task
                        for item in list(
                            dict(context.state.get("decision_matrix") or {}).get("items") or []
                        )
                        for task in list(item.get("verification_tasks") or [])
                    ],
                ],
        )
        report = str(result.get("report") or "")
        study_markdown = str(context.state.get("study_plan_markdown") or "")
        if study_markdown and study_markdown not in report:
            report = f"{report.rstrip()}\n\n## 复习计划\n\n{study_markdown}".strip()
        context.state["report"] = report
        context.state["report_meta"] = dict(result.get("report_meta") or {})
        validation = self.report_quality_service.validate(
            report=report,
            decision_matrix=dict(context.state.get("decision_matrix") or {}),
            risk_review=dict(context.state.get("risk_review") or {}),
        )
        context.state["report_validation"] = validation
        context.state["validation"] = validation
        return self._tool_contract(
            status="complete" if validation.get("passed") else "partial",
            covered=["岗位分析报告"] if validation.get("passed") else [],
            missing=list(validation.get("missing_requirements") or []),
            confidence="high" if validation.get("passed") else "low",
            next_actions=list(validation.get("next_actions") or []),
            data={
                "report": report,
                "report_meta": context.state["report_meta"],
                "decision_matrix": dict(context.state.get("decision_matrix") or {}),
                "task_contract": dict(context.state.get("task_contract") or {}),
                "validation": validation,
                "report_validation": validation,
            },
        )

    def _tool_contract(
        self,
        *,
        status: str,
        covered: list[str],
        missing: list[str],
        confidence: str,
        next_actions: list[str],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status": status,
            "covered": list(dict.fromkeys(str(item) for item in covered if item)),
            "missing": list(dict.fromkeys(str(item) for item in missing if item)),
            "confidence": confidence,
            "next_actions": list(dict.fromkeys(str(item) for item in next_actions if item)),
            **data,
        }

    def _position_label(self, position: dict[str, Any]) -> str:
        return " / ".join(
            str(position.get(key) or "").strip()
            for key in ("department_name", "office_name", "job_title")
            if str(position.get(key) or "").strip()
        ) or "未知岗位"

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
                "decision_matrix": dict(state.get("decision_matrix") or {}),
                "evidence_inventory": dict(state.get("evidence_inventory") or {}),
                "task_contract": dict(state.get("task_contract") or {}),
                "validation": dict(state.get("validation") or {}),
                "report_validation": dict(state.get("report_validation") or {}),
            },
            "recommendations": list(state.get("recommendations") or []),
            "risk_review": dict(state.get("risk_review") or {}),
            "study_plan": dict(state.get("study_plan") or {}),
            "decision_matrix": dict(state.get("decision_matrix") or {}),
            "evidence_inventory": dict(state.get("evidence_inventory") or {}),
            "task_contract": dict(state.get("task_contract") or {}),
            "validation": dict(state.get("validation") or {}),
            "report_validation": dict(state.get("report_validation") or {}),
            "needs_more_info": bool(state.get("needs_more_info", False)),
            "missing_fields": list(state.get("missing_fields") or []),
            "clarifying_questions": list(state.get("clarifying_questions") or []),
        }

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        snapshot = dict(context.get("snapshot") or {})
        return (
            f"请基于固定岗位快照「{snapshot.get('title') or '岗位快照'}」生成岗位分析报告。"
            "这是一个 Agent Loop：先加载 position-planning skill 并制定计划；再根据工具返回的 missing、confidence 和 next_actions 自主补充岗位历史、政策证据和隐性条件；然后生成岗位决策矩阵，完成报告质量校验后再输出中文 Markdown。"
            "禁止只罗列岗位，必须给出冲刺、主攻、保底、谨慎或排除分层，并说明岗位之间为什么不同。"
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
