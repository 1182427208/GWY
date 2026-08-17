from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
    _HAS_LANGGRAPH = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    END = START = None
    StateGraph = None
    _HAS_LANGGRAPH = False

from app.gwy.skills.position_analysis_skills import cleanup_analysis_report

if TYPE_CHECKING:
    from app.gwy.llm.chat_service import ChatService


REPORT_GENERATOR_SYSTEM_PROMPT = """
你是 GwyPilot 的岗位分析报告生成器。

任务目标
- 根据结构化岗位事实、风险复核结果和报告提纲生成 Markdown 报告。
- 先给结论，再给依据，再给风险提示，最后给下一步建议。
- 语言要清楚、稳一点、像一个懂公考流程的分析顾问。

输出要求
- 只输出 Markdown。
- 不要输出隐藏推理链，不要把草稿过程写出来。
- 不要编造任何公告、条件、分数线或招录信息。
- 如果信息不足，要明确写“无法确认”或“需要补充信息”。
- 尽量保留结构化小标题，避免长段空话。
""".strip()


class ReportState(TypedDict, total=False):
    title: str
    recommendations: list[dict[str, Any]]
    risk_review: dict[str, Any]
    decision_matrix: dict[str, Any]
    evidence_inventory: dict[str, Any]
    verification_tasks: list[str]
    outline: list[str]
    reflection: dict[str, Any]
    validation: dict[str, Any]
    sections: list[str]
    report: str
    report_meta: dict[str, Any]
    trace: list[dict[str, Any]]


class _FallbackGraph:
    def __init__(self, agent: ReportGeneratorAgent) -> None:
        self._agent = agent

    def invoke(self, state: ReportState) -> dict[str, Any]:
        current_state: dict[str, Any] = dict(state)
        current_state.update(self._agent._node_plan(current_state))
        current_state.update(self._agent._node_react(current_state))
        current_state.update(self._agent._node_reflect(current_state))
        current_state.update(self._agent._node_validate(current_state))
        return current_state


@dataclass(slots=True)
class ReportGeneratorAgent:
    chat_service: ChatService | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        *,
        title: str,
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
        decision_matrix: dict[str, Any] | None = None,
        evidence_inventory: dict[str, Any] | None = None,
        verification_tasks: list[str] | None = None,
    ) -> dict[str, Any]:
        state: ReportState = {
            "title": title,
            "recommendations": recommendations,
            "risk_review": risk_review,
            "decision_matrix": dict(decision_matrix or {}),
            "evidence_inventory": dict(evidence_inventory or {}),
            "verification_tasks": list(verification_tasks or []),
            "trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self) -> Any:
        if not _HAS_LANGGRAPH:
            return _FallbackGraph(self)
        builder = StateGraph(ReportState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("react", self._node_react)
        builder.add_node("reflect", self._node_reflect)
        builder.add_node("validate", self._node_validate)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "react")
        builder.add_edge("react", "reflect")
        builder.add_edge("reflect", "validate")
        builder.add_edge("validate", END)
        return builder.compile()

    def _node_plan(self, state: ReportState) -> dict[str, Any]:
        recommendations = list(state.get("recommendations") or [])
        risk_review = dict(state.get("risk_review") or {})
        outline = [
            "直接结论",
            "判断依据",
            "风险提醒",
            "下一步建议",
        ]
        if recommendations:
            outline.insert(2, f"Top 岗位（{min(5, len(recommendations))} 个）")
        if risk_review.get("risk_level") == "high":
            outline.insert(3, "高风险复核点")

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="plan",
                status="done",
                detail="已生成报告提纲",
                started_at=time.perf_counter(),
                inputs_summary={
                    "recommendation_count": len(recommendations),
                    "risk_level": risk_review.get("risk_level"),
                },
                outputs_summary={
                    "outline_count": len(outline),
                },
            )
        )
        return {"outline": outline, "trace": trace}

    def _node_react(self, state: ReportState) -> dict[str, Any]:
        started_at = time.perf_counter()
        title = str(state.get("title") or "岗位推荐报告")
        outline = list(state.get("outline") or [])
        recommendations = list(state.get("recommendations") or [])
        risk_review = dict(state.get("risk_review") or {})
        decision_matrix = dict(state.get("decision_matrix") or {})
        evidence_inventory = dict(state.get("evidence_inventory") or {})
        verification_tasks = list(state.get("verification_tasks") or [])

        draft = self._build_report_draft_v2(
            title=title,
            outline=outline,
            recommendations=recommendations,
            risk_review=risk_review,
            decision_matrix=decision_matrix,
            evidence_inventory=evidence_inventory,
            verification_tasks=verification_tasks,
        )

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="draft_report",
                status="done",
                detail="已基于结构化数据生成报告草稿",
                started_at=started_at,
                inputs_summary={
                    "recommendation_count": len(recommendations),
                    "risk_item_count": len(risk_review.get("risk_items") or []),
                    "outline_count": len(outline),
                },
                outputs_summary={
                    "draft_length": len(draft),
                },
            )
        )

        polished = draft
        llm_started = time.perf_counter()
        used_llm = False
        if self.chat_service is not None and draft.strip():
            try:
                messages = [
                    {
                        "role": "system",
                        "content": REPORT_GENERATOR_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": self._build_llm_prompt(
                            title=title,
                            outline=outline,
                            recommendations=recommendations,
                            risk_review=risk_review,
                            decision_matrix=decision_matrix,
                            evidence_inventory=evidence_inventory,
                            verification_tasks=verification_tasks,
                            draft=draft,
                        ),
                    },
                ]
                polished_candidate = self.chat_service.chat_completion(
                    messages,
                    temperature=0.2,
                )
                polished_candidate = cleanup_analysis_report(
                    str(polished_candidate or "")
                )
                if polished_candidate and len(polished_candidate) >= max(
                    40,
                    len(draft) // 2,
                ):
                    polished = polished_candidate
                    used_llm = True
            except Exception as exc:  # pragma: no cover - defensive fallback
                trace.append(
                    self._trace_entry(
                        step="llm_polish",
                        status="failed",
                        detail=f"模型润色失败: {exc}",
                        started_at=llm_started,
                        inputs_summary={
                            "prompt_length": len(
                                self._build_llm_prompt(
                                    title=title,
                                    outline=outline,
                                    recommendations=recommendations,
                                    risk_review=risk_review,
                                    decision_matrix=decision_matrix,
                                    evidence_inventory=evidence_inventory,
                                    verification_tasks=verification_tasks,
                                    draft=draft,
                                )
                            ),
                        },
                        outputs_summary={
                            "used_llm": False,
                        },
                    )
                )
            else:
                trace.append(
                    self._trace_entry(
                        step="llm_polish",
                        status="done",
                        detail="已调用模型整理报告表达",
                        started_at=llm_started,
                        inputs_summary={
                            "prompt_length": len(
                                self._build_llm_prompt(
                                    title=title,
                                    outline=outline,
                                    recommendations=recommendations,
                                    risk_review=risk_review,
                                    decision_matrix=decision_matrix,
                                    evidence_inventory=evidence_inventory,
                                    verification_tasks=verification_tasks,
                                    draft=draft,
                                )
                            ),
                        },
                        outputs_summary={
                            "final_length": len(polished),
                            "used_llm": used_llm,
                            "model_name": self._resolve_model_name(),
                        },
                    )
                )
        elif self.chat_service is not None:
            trace.append(
                self._trace_entry(
                    step="llm_polish",
                    status="skipped",
                    detail="草稿为空，跳过模型润色",
                    started_at=llm_started,
                    outputs_summary={
                        "used_llm": False,
                    },
                )
            )
        else:
            trace.append(
                self._trace_entry(
                    step="llm_polish",
                    status="skipped",
                    detail="未配置模型服务，使用本地草稿",
                    started_at=llm_started,
                    outputs_summary={
                        "used_llm": False,
                    },
                )
            )

        report_meta = {
            "provider": "SiliconFlow" if self.chat_service is not None else "local",
            "model_name": self._resolve_model_name(),
            "used_llm": used_llm,
            "draft_length": len(draft),
            "final_length": len(polished),
        }

        return {
            "sections": [draft],
            "report": polished,
            "trace": trace,
            "report_meta": report_meta,
        }

    def _node_review(self, state: ReportState) -> dict[str, Any]:
        started_at = time.perf_counter()
        report = str(state.get("report") or "")
        outline = list(state.get("outline") or [])
        missing_sections = [section for section in outline if section not in report]

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="review",
                status="done",
                detail="已复核报告结构和完整性",
                started_at=started_at,
                inputs_summary={
                    "outline_count": len(outline),
                    "report_length": len(report),
                },
                outputs_summary={
                    "missing_section_count": len(missing_sections),
                    "passed": not missing_sections,
                },
            )
        )

        if missing_sections:
            report = f"{report}\n\n> Review note: missing sections: {', '.join(missing_sections)}"

        return {"report": report, "trace": trace}

    def _node_solve(self, state: ReportState) -> dict[str, Any]:
        return self._node_react(state)

    def _node_reflect(self, state: ReportState) -> dict[str, Any]:
        started_at = time.perf_counter()
        report = str(state.get("report") or "")
        outline = list(state.get("outline") or [])
        missing_sections = [section for section in outline if section not in report]
        evidence_inventory = dict(state.get("evidence_inventory") or {})
        verification_tasks = list(state.get("verification_tasks") or [])
        reflection = {
            "status": "needs_revision" if missing_sections else "ok",
            "missing_sections": missing_sections,
            "missing_evidence": list(evidence_inventory.get("missing") or []),
            "verification_task_count": len(verification_tasks),
            "next_action": "补齐缺失章节并重写结论" if missing_sections else "交给 validator 进行最终检查",
        }

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="reflect",
                status=reflection["status"],
                detail="宸叉牴鎹ぇ缁撴瀯銆佽瘉鎹拰鏍稿疄浠诲姟鍋氬鍐嶈",
                started_at=started_at,
                inputs_summary={
                    "outline_count": len(outline),
                    "report_length": len(report),
                    "verification_task_count": len(verification_tasks),
                },
                outputs_summary={
                    "missing_section_count": len(missing_sections),
                    "missing_evidence_count": len(reflection["missing_evidence"]),
                    "next_action": reflection["next_action"],
                },
            )
        )

        if missing_sections:
            report = f"{report}\n\n> Review note: missing sections: {', '.join(missing_sections)}"

        return {"report": report, "reflection": reflection, "trace": trace}

    def _node_validate(self, state: ReportState) -> dict[str, Any]:
        started_at = time.perf_counter()
        report = str(state.get("report") or "")
        outline = list(state.get("outline") or [])
        reflection = dict(state.get("reflection") or {})
        validation = self._validate_report(
            report=report,
            outline=outline,
            reflection=reflection,
        )

        trace = list(state.get("trace") or [])
        trace.append(
            self._trace_entry(
                step="validate",
                status=validation["status"],
                detail=validation["reason"],
                started_at=started_at,
                inputs_summary={
                    "outline_count": len(outline),
                    "report_length": len(report),
                },
                outputs_summary={
                    "passed": validation["passed"],
                    "issue_count": len(validation["issues"]),
                },
            )
        )

        report_meta = dict(state.get("report_meta") or {})
        report_meta["validation_status"] = validation["status"]
        report_meta["validation_issues"] = validation["issues"]

        return {"validation": validation, "report_meta": report_meta, "trace": trace}

    def _build_report_draft(
        self,
        *,
        title: str,
        outline: list[str],
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
        decision_matrix: dict[str, Any],
        evidence_inventory: dict[str, Any],
        verification_tasks: list[str],
    ) -> str:
        lines: list[str] = [f"# {title}", ""]
        for section in outline:
            if section == "直接结论":
                lines.extend(
                    [
                        "## 直接结论",
                        self._build_conclusion(recommendations, risk_review),
                        "",
                    ]
                )
                continue
            if section == "判断依据":
                lines.extend(
                    [
                        "## 判断依据",
                        self._build_reasoning_block(recommendations, risk_review),
                        "",
                    ]
                )
                continue
            if section.startswith("Top 岗位"):
                lines.append(f"## {section}")
                for index, item in enumerate(recommendations[:5], start=1):
                    lines.append(
                        f"{index}. {item.get('department_name') or item.get('job_title') or '未知岗位'}"
                        f" | 分数 {item.get('score', 0)}"
                        f" | 风险 {item.get('risk_level') or 'unknown'}"
                    )
                lines.append("")
                continue
            if section == "高风险复核点":
                lines.extend(
                    [
                        "## 高风险复核点",
                        "- 当前岗位中存在高风险信号时，建议逐条回看公告原文并人工确认。",
                        "",
                    ]
                )
                continue
            if section == "风险提醒":
                lines.append("## 风险提醒")
                risk_items = list(risk_review.get("risk_items") or [])
                if not risk_items:
                    lines.append("- 暂未识别到明显风险。")
                for item in risk_items[:5]:
                    lines.append(
                        f"- {item.get('risk_type')}: {item.get('explanation') or item.get('evidence') or '需核查'}"
                    )
                lines.append("")
                continue
            if section == "下一步建议":
                lines.extend(
                    [
                        "## 下一步建议",
                        "- 先核对学历、学位、专业、政治面貌、基层经历等硬性条件。",
                        "- 对有人工核实要求的岗位，优先回看官方公告和职位表原文。",
                        "",
                    ]
                )
        return "\n".join(lines).strip()

    def _build_conclusion(
        self,
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> str:
        if not recommendations:
            return "- 当前没有可直接推荐的岗位，需要先补充筛选条件或岗位列表。"
        risk_level = str(risk_review.get("risk_level") or "unknown")
        return (
            f"- 当前可见岗位里有 {len(recommendations)} 条候选，整体风险等级为 {risk_level}。"
        )

    def _build_reasoning_block(
        self,
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> str:
        lines = [
            f"- 结构化筛选结果保留了 {len(recommendations)} 条候选岗位。",
            f"- 风险复核阶段识别到 {len(risk_review.get('risk_items') or [])} 项风险提示。",
        ]
        return "\n".join(lines)

    def _build_llm_prompt(
        self,
        *,
        title: str,
        outline: list[str],
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
        decision_matrix: dict[str, Any],
        evidence_inventory: dict[str, Any],
        verification_tasks: list[str],
        draft: str,
    ) -> str:
        payload = {
            "title": title,
            "outline": outline,
            "recommendations": recommendations[:5],
            "risk_review": risk_review,
            "decision_matrix": decision_matrix,
            "evidence_inventory": evidence_inventory,
            "verification_tasks": verification_tasks,
            "draft": draft,
        }
        return (
            "请将下面的结构化输入整理为一份可直接支持报考决策的中文 Markdown 岗位分析报告。\n"
            "先给直接结论，再给冲刺、主攻、保底、谨慎、排除分层和岗位横向比较。\n"
            "每个岗位必须说明分层原因、最大风险、数据置信度、具体核验材料与动作，以及核验后如何改变结论。\n"
            "不能把所有岗位都写成推荐；不能编造分数、报录比、进面分、概率或公告条件。未知数据必须保留为未知并转成具体补证任务，风险按岗位和风险类型去重。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"
        )

    def _build_report_draft_v2(
        self,
        *,
        title: str,
        outline: list[str],
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
        decision_matrix: dict[str, Any],
        evidence_inventory: dict[str, Any],
        verification_tasks: list[str],
    ) -> str:
        lines: list[str] = [f"# {title}", ""]
        lines.extend(
            [
                "## 直接结论",
                self._build_conclusion(recommendations, risk_review),
                "",
                "## 判断依据",
                self._build_reasoning_block(recommendations, risk_review),
                "",
                "## 岗位决策分层",
                *self._build_decision_matrix_block(decision_matrix),
                "",
                "## 岗位横向比较",
                *self._build_comparison_block(decision_matrix),
                "",
                "## 风险提醒",
                self._build_risk_block(recommendations, risk_review),
                "",
                "## 岗位逐条分析",
            ]
        )
        if recommendations:
            for index, item in enumerate(recommendations, start=1):
                lines.extend(self._build_position_analysis_block(index, item))
        else:
            lines.append("- 当前没有可分析的岗位。")

        lines.extend(
            [
                "",
                "## 最终推荐",
                self._build_final_recommendation_block(recommendations, risk_review),
                "",
                "## 下一步建议",
                self._build_next_steps_block(
                    recommendations,
                    risk_review,
                    verification_tasks=verification_tasks,
                    evidence_inventory=evidence_inventory,
                ),
            ]
        )

        if outline:
            lines.extend(["", "## 报告结构", *[f"- {item}" for item in outline]])
        return "\n".join(lines).strip()

    def _build_decision_matrix_block(self, matrix: dict[str, Any]) -> list[str]:
        items = list(matrix.get("items") or [])
        if not items:
            return ["- 当前尚未形成结构化岗位决策，需要先完成岗位研究。"]
        lines: list[str] = []
        tier_labels = {"sprint": "冲刺", "primary": "主攻", "backup": "保底", "caution": "谨慎", "exclude": "排除"}
        for index, item in enumerate(items[:10], start=1):
            tier = str(item.get("tier") or "unknown")
            lines.append(
                f"- {index}. {item.get('label') or item.get('position_id') or '未知岗位'} | "
                f"分层：{tier_labels.get(tier, tier)} | 匹配度：{item.get('fit_score', '未知')} | "
                f"竞争：{item.get('competition_level') or '未知'} | "
                f"投入：{item.get('preparation_cost') or '未知'} | "
                f"置信度：{item.get('confidence') or '未知'}"
            )
            for reason in list(item.get("reasons") or [])[:2]:
                lines.append(f"  - 主要依据：{reason}")
            for unknown in list(item.get("unknowns") or [])[:2]:
                lines.append(f"  - 数据缺口：{unknown}")
        return lines

    def _build_comparison_block(self, matrix: dict[str, Any]) -> list[str]:
        items = list(matrix.get("items") or [])
        if len(items) < 2:
            return ["- 当前候选岗位不足两个，暂时无法进行横向比较。"]
        ranked = sorted(
            items,
            key=lambda item: (
                self._tier_order(str(item.get("tier") or "")),
                -int(item.get("fit_score") or 0),
            ),
        )
        first = ranked[0].get("label") or ranked[0].get("position_id") or "未知岗位"
        second = ranked[1].get("label") or ranked[1].get("position_id") or "未知岗位"
        return [f"- 当前优先级：{first} 高于 {second}，依据是分层、匹配度、竞争信息和证据置信度。"]

    def _tier_order(self, tier: str) -> int:
        return {"primary": 0, "backup": 1, "sprint": 1, "caution": 2, "exclude": 3}.get(tier, 4)

    def _build_position_analysis_block(
        self,
        rank: int,
        item: dict[str, Any],
    ) -> list[str]:
        score = item.get("score", 0)
        recommend_level = str(item.get("recommend_level") or "weak_match")
        risk_level = str(item.get("risk_level") or "unknown")
        position_label = self._format_position_label(item)
        reasons = self._format_text_items(item.get("reasons"))
        risks = self._format_text_items(item.get("risks"))
        recruit_count = item.get("recruit_count")
        interview_ratio = item.get("interview_ratio")
        remark_text = str(item.get("remarks") or "").strip()
        lines = [
            f"### {rank}. {position_label}",
            f"- 匹配度：{score}",
            f"- 推荐等级：{recommend_level}",
            f"- 风险等级：{risk_level}",
            f"- 招录人数：{recruit_count if recruit_count not in (None, '') else '缺失'}",
            f"- 当前报录比：{interview_ratio if interview_ratio not in (None, '') else '缺失'}",
            f"- 岗位信息：{self._format_position_info(item)}",
        ]
        if reasons:
            lines.append("#### 主要匹配点")
            for reason in reasons[:4]:
                lines.append(f"- {reason}")
        if risks:
            lines.append("#### 风险提示")
            for risk in risks[:4]:
                lines.append(f"- {risk}")
        lines.append("#### 报考结论")
        lines.append(f"- {self._recommendation_conclusion(recommend_level, risk_level, item)}")
        lines.append("#### 核验事项")
        lines.append("- 专业名称、学历学位、政治面貌、基层经历、备注限制要逐条核对。")
        if remark_text:
            lines.append(f"- 备注原文：{remark_text[:120]}")
        lines.append("")
        return lines

    def _build_final_recommendation_block(
        self,
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> str:
        if not recommendations:
            return "- 当前没有足够明确的岗位可排序推荐，建议先补充筛选条件。"

        lines = []
        for index, item in enumerate(recommendations[:5], start=1):
            label = self._format_position_label(item)
            lines.append(
                f"{index}. {label} | 匹配度 {item.get('score', 0)} | 风险 {item.get('risk_level') or 'unknown'}"
            )
        if risk_review.get("risk_items"):
            lines.append(
                f"- 当前共有 {len(risk_review.get('risk_items') or [])} 条风险提示，需要在报考前逐一复核。"
            )
        return "\n".join(lines)

    def _build_next_steps_block(
        self,
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
        *,
        verification_tasks: list[str],
        evidence_inventory: dict[str, Any],
    ) -> str:
        lines = [
            "- 先确认学历、学位、专业、政治面貌、基层经历这些硬性条件。",
            "- 再按推荐顺序看前 3 个岗位的备注、地区和招录人数。",
            "- 如果岗位备注里有人工核验、资格审查或专业测试要求，优先以公告原文复核。",
        ]
        if risk_review.get("risk_items"):
            lines.append("- 对风险等级高的岗位，先复核风险点再决定是否作为主报。")
        if len(recommendations) > 3:
            lines.append("- 如果想缩小范围，可以继续按地区、部门或竞争强度再筛一轮。")
        for task in verification_tasks[:6]:
            lines.append(f"- 核验任务：{task}")
        for missing in list(evidence_inventory.get("missing") or [])[:6]:
            lines.append(f"- 待补证据：{missing}")
        return "\n".join(lines)

    def _build_risk_block(
        self,
        recommendations: list[dict[str, Any]],
        risk_review: dict[str, Any],
    ) -> str:
        risk_items = list(risk_review.get("risk_items") or [])
        if not risk_items:
            return "- 当前未发现明显风险，但仍建议以公告原文和资格审查结果为准。"

        lines = []
        for item in risk_items[:5]:
            lines.append(
                f"- {item.get('risk_type')}: {item.get('explanation') or item.get('evidence') or '需要复核'}"
            )
        if recommendations and any(
            str(item.get("risk_level") or "").lower() == "high"
            for item in recommendations[:5]
        ):
            lines.append("- 高风险岗位建议作为备选，不要直接当主报。")
        return "\n".join(lines)

    def _format_text_items(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        result: list[str] = []
        for item in values:
            if isinstance(item, dict):
                text = str(
                    item.get("text")
                    or item.get("explanation")
                    or item.get("evidence")
                    or ""
                ).strip()
                if text:
                    result.append(text)
            else:
                text = str(item).strip()
                if text:
                    result.append(text)
        return result

    def _format_position_label(self, item: dict[str, Any]) -> str:
        department = str(item.get("department_name") or "").strip()
        office = str(item.get("office_name") or "").strip()
        job_title = str(item.get("job_title") or "").strip()
        parts = [part for part in (department, office, job_title) if part]
        return " / ".join(parts) if parts else "未知岗位"

    def _format_position_info(self, item: dict[str, Any]) -> str:
        pieces = [
            f"代码 {item.get('position_code') or '未知'}",
            f"地区 {item.get('work_location') or item.get('position_distribution') or '未知'}",
            f"学历 {item.get('education_requirement') or '未知'}",
            f"学位 {item.get('degree_requirement') or '未知'}",
            f"专业 {item.get('major_requirement') or '未知'}",
        ]
        return "；".join(pieces)

    def _recommendation_conclusion(
        self,
        recommend_level: str,
        risk_level: str,
        item: dict[str, Any],
    ) -> str:
        if recommend_level in {"strong_match", "good_match"} and risk_level in {
            "low",
            "medium",
        }:
            return "可以优先考虑，适合放进主报或重点备选。"
        if risk_level == "high" or bool(item.get("need_manual_confirm")):
            return "能报不等于值得报，建议先复核备注和资格条件。"
        return "可作为备选岗位，适合进一步核对条件后再决定。"

    def _resolve_model_name(self) -> str | None:
        if self.chat_service is None:
            return None
        client = getattr(self.chat_service, "client", None)
        model_name = getattr(client, "chat_model", None)
        return str(model_name) if model_name else None

    def _trace_entry(
        self,
        *,
        step: str,
        status: str,
        detail: str,
        started_at: float,
        inputs_summary: dict[str, Any] | None = None,
        outputs_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
        payload = {
            "step": step,
            "status": status,
            "detail": detail,
            "elapsed_ms": elapsed_ms,
            "inputs_summary": inputs_summary or {},
            "outputs_summary": outputs_summary or {},
            "evidence_refs": [],
        }
        payload.update(self._trace_context(step))
        return payload

    def _trace_context(self, step: str) -> dict[str, Any]:
        mapping = {
            "plan": {
                "agent": "ReportGeneratorAgent",
                "skill": "report_outline_planning",
                "tool": "ArtifactComposer",
                "backend": "Structured markdown composition",
            },
            "draft_report": {
                "agent": "ReportGeneratorAgent",
                "skill": "report_drafting",
                "tool": "ArtifactComposer",
                "backend": "Structured markdown composition",
            },
            "llm_polish": {
                "agent": "ReportGeneratorAgent",
                "skill": "reflection",
                "tool": "ChatService",
                "backend": "LLM polish fallback",
            },
            "reflect": {
                "agent": "ReportGeneratorAgent",
                "skill": "reflection",
                "tool": "ReportReviewer",
                "backend": "Consistency and coverage review",
            },
            "validate": {
                "agent": "ReportGeneratorAgent",
                "skill": "artifact_validation",
                "tool": "ReportValidator",
                "backend": "Markdown structure and evidence consistency check",
            },
            "review": {
                "agent": "ReportGeneratorAgent",
                "skill": "artifact_validation",
                "tool": "ReportValidator",
                "backend": "Markdown structure and evidence consistency check",
            },
        }
        return mapping.get(step, {"agent": "ReportGeneratorAgent"})

    def _validate_report(
        self,
        *,
        report: str,
        outline: list[str],
        reflection: dict[str, Any],
    ) -> dict[str, Any]:
        issues: list[str] = []
        if not report.strip():
            issues.append("report_empty")
        for section in outline:
            if section not in report:
                issues.append(f"missing_section:{section}")
        for missing in list(reflection.get("missing_evidence") or []):
            issues.append(f"missing_evidence:{missing}")
        passed = not issues
        return {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "issues": issues,
            "reason": "report validation passed" if passed else "report validation failed",
        }
