"""LangGraph agent for study plan generation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.gwy.llm.chat_service import ChatService
from app.gwy.prompts.study_plan import (
    STUDY_PLAN_SYSTEM_PROMPT,
    STUDY_PLAN_USER_PROMPT_TEMPLATE,
)
from app.gwy.skills.study_plan_skills import (
    analyze_exam_subjects,
    build_subject_checklist,
    estimate_exam_date,
    format_study_plan_markdown,
    generate_phase_schedule,
)

logger = logging.getLogger(__name__)


class StudyPlanState(TypedDict, total=False):
    user_profile: dict[str, Any]
    recommendations: list[dict[str, Any]]
    exam_type: str
    exam_year: int | None
    exam_date: str
    study_hours_per_day: int
    total_weeks: int
    subjects: dict[str, Any]
    phases: list[dict[str, Any]]
    subject_checklist: dict[str, Any]
    tasks: list[dict[str, Any]]
    llm_plan_json: dict[str, Any]
    plan_title: str
    plan_markdown: str
    study_tips: list[str]
    reflection: dict[str, Any]
    validation: dict[str, Any]
    status: str
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class StudyPlanAgent:
    chat_service: ChatService | None = None
    graph: Any = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self.chat_service = self.chat_service or ChatService()
        self.graph = None

    def run(
        self,
        *,
        user_profile: dict[str, Any],
        recommendations: list[dict[str, Any]],
        exam_type: str = "??",
        exam_year: int | None = None,
        study_hours_per_day: int = 4,
    ) -> dict[str, Any]:
        state: StudyPlanState = {
            "user_profile": dict(user_profile or {}),
            "recommendations": list(recommendations or []),
            "exam_type": exam_type,
            "exam_year": exam_year,
            "study_hours_per_day": study_hours_per_day,
            "trace": [],
            "status": "running",
        }
        state.update(self._node_analyze_profile(state))
        state.update(self._node_plan_phases(state))
        state.update(self._node_generate_subjects(state))
        state.update(self._node_schedule_tasks(state))
        state.update(self._node_compose_plan(state))
        state.update(self._node_reflect_plan(state))
        state.update(self._node_validate_plan(state))
        return state

    # ?? nodes ????????????????????????????????????????????????????

    def _node_analyze_profile(self, state: StudyPlanState) -> dict[str, Any]:
        profile = state.get("user_profile") or {}
        recommendations = state.get("recommendations") or []
        exam_type = str(state.get("exam_type") or "??")
        exam_year = state.get("exam_year") or None

        exam_date = estimate_exam_date(exam_year=exam_year)
        subjects_result = analyze_exam_subjects(
            recommendations=recommendations,
            user_profile=profile,
            exam_type=exam_type,
        )

        self._record_trace(state, "analyze_profile", {
            "agent": "StudyPlanAgent",
            "skill": "analyze_exam_subjects",
            "exam_date": str(exam_date),
            "subjects": list(subjects_result.get("subjects", {}).keys()),
        })

        return {
            "exam_date": str(exam_date),
            "subjects": subjects_result.get("subjects", {}),
        }

    def _node_plan_phases(self, state: StudyPlanState) -> dict[str, Any]:
        import datetime as dt
        profile = state.get("user_profile") or {}
        exam_date_str = state.get("exam_date", "")
        study_hours = state.get("study_hours_per_day", 4)

        try:
            exam_date = dt.date.fromisoformat(exam_date_str)
        except (ValueError, TypeError):
            exam_date = estimate_exam_date(exam_year=None)

        phases = generate_phase_schedule(
            exam_date=exam_date,
            start_date=dt.date.today(),
            study_hours_per_day=study_hours,
            user_profile=profile,
        )

        total_weeks = max(p["week_end"] for p in phases) if phases else 12

        self._record_trace(state, "plan_phases", {
            "agent": "StudyPlanAgent",
            "skill": "generate_phase_schedule",
            "phase_count": len(phases),
            "total_weeks": total_weeks,
        })

        return {"phases": phases, "total_weeks": total_weeks}

    def _node_generate_subjects(self, state: StudyPlanState) -> dict[str, Any]:
        profile = state.get("user_profile") or {}
        subjects = state.get("subjects") or {}

        checklist = build_subject_checklist(
            subjects=subjects,
            user_profile=profile,
        )

        total_weeks = state.get("total_weeks", 12)
        hours_per_day = state.get("study_hours_per_day", 4)
        total_hours = total_weeks * 7 * hours_per_day

        for name, info in checklist.items():
            weight = info.get("weight_percent", 50 if name != "????" else 20)
            info["total_hours"] = int(total_hours * weight / 100)

        self._record_trace(state, "generate_subjects", {
            "agent": "StudyPlanAgent",
            "skill": "build_subject_checklist",
            "subject_count": len(checklist),
        })

        return {"subject_checklist": checklist}

    def _node_schedule_tasks(self, state: StudyPlanState) -> dict[str, Any]:
        subjects = state.get("subjects") or {}
        phases = state.get("phases") or []
        hours_per_day = state.get("study_hours_per_day", 4)
        all_tasks: list[dict[str, Any]] = []

        for phase in phases:
            phase_weeks = range(phase["week_start"], phase["week_end"] + 1)
            phase_hours = phase.get("study_hours_per_day", hours_per_day)

            for week in phase_weeks:
                for day in range(1, 8):
                    if day == 7:
                        rest_title = "周末复盘与调整"
                        all_tasks.append({
                            "week_number": week,
                            "day_of_week": day,
                            "subject": "休整",
                            "task_title": rest_title,
                            "task_description": "回顾本周错题与笔记，整理薄弱点并为下周做调整。",
                            "estimated_minutes": phase_hours * 60 // 2,
                            "priority": 3,
                            "completed": False,
                        })
                        continue

                    subject_keys = list(subjects.keys())
                    if not subject_keys:
                        continue
                    subject_idx = (day - 1) % len(subject_keys)
                    subject = subject_keys[subject_idx]

                    if subject == "行测":
                        module_keys = list(
                            subjects[subject].get("modules", {}).keys()
                        )
                        mod_idx = ((week - 1) * 6 + day - 1) % max(len(module_keys), 1)
                        module_name = module_keys[mod_idx]
                        task_title = f"行测 {module_name} 专项训练"
                        desc = f"{phase['phase_name']} - 聚焦 {module_name} 进行专项训练。"
                    elif subject == "申论":
                        role = "基础练习" if day <= 4 else "写作训练"
                        task_title = f"申论 {role}"
                        desc = f"{phase['phase_name']} - 完成 {role} 与素材整理。"
                    elif subject == "专业科目":
                        task_title = "专业科目基础梳理"
                        desc = f"{phase['phase_name']} - 梳理专业知识框架并完成核心概念回顾。"
                    else:
                        task_title = f"{subject} 学习任务"
                        desc = f"{phase['phase_name']} - 完成 {subject} 相关学习与练习。"

                    all_tasks.append({
                        "week_number": week,
                        "day_of_week": day,
                        "subject": subject,
                        "task_title": task_title,
                        "task_description": desc,
                        "estimated_minutes": phase_hours * 60,
                        "priority": 1,
                        "completed": False,
                    })

        self._record_trace(state, "schedule_tasks", {
            "agent": "StudyPlanAgent",
            "skill": "format_study_plan_markdown",
            "task_count": len(all_tasks),
        })

        return {"tasks": all_tasks}

    def _node_compose_plan(self, state: StudyPlanState) -> dict[str, Any]:
        profile = state.get("user_profile") or {}
        subjects = state.get("subject_checklist") or {}
        phases = state.get("phases") or []
        tasks = state.get("tasks") or []
        exam_date = state.get("exam_date", "")
        study_hours = state.get("study_hours_per_day", 4)
        total_weeks = state.get("total_weeks", 12)
        exam_type = state.get("exam_type", "??")

        # Try LLM-enhanced title and tips
        plan_json: dict[str, Any] = {}
        study_tips: list[str] = []

        chat = self.chat_service
        if chat is not None:
            try:
                education = profile.get("education") or "??"
                major = profile.get("major") or "??"
                regions = profile.get("target_regions") or []
                regions_str = "?".join(regions) if regions else "??"

                positions_str = "\n".join(
                    f"- {p.get('department_name', '')} {p.get('job_title', '')}"
                    for p in (state.get("recommendations") or [])[:5]
                ) or "????????"

                prompt = STUDY_PLAN_USER_PROMPT_TEMPLATE.format(
                    education=education,
                    major=major,
                    regions=regions_str,
                    study_hours=study_hours,
                    positions=positions_str,
                    exam_type=exam_type,
                    exam_date=exam_date,
                )
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": STUDY_PLAN_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                llm_response = chat.chat_completion(messages, temperature=0.3)
                if llm_response.strip():
                    plan_json = json.loads(llm_response)
                study_tips = plan_json.get("study_tips", [])
            except Exception:
                logger.exception("LLM study plan enhancement failed, using defaults")

        plan_title = plan_json.get("title") or f"{exam_type}??????"

        study_plan_context = {
            "exam_type": exam_type,
            "estimated_exam_date": exam_date,
            "study_hours_per_day": study_hours,
            "total_weeks": total_weeks,
        }

        plan_markdown = format_study_plan_markdown(
            title=plan_title,
            study_plan=study_plan_context,
            phases=phases,
            subjects=subjects,
            tasks=tasks,
        )

        self._record_trace(state, "compose_plan", {
            "agent": "StudyPlanAgent",
            "skill": "artifact_composition",
            "status": "completed",
            "plan_title": plan_title,
            "phase_count": len(phases),
            "task_count": len(tasks),
            "used_llm": bool(plan_json),
        })

        return {
            "plan_title": plan_title,
            "plan_markdown": plan_markdown,
            "llm_plan_json": plan_json,
            "study_tips": study_tips,
            "status": "completed",
        }

    def _node_reflect_plan(self, state: StudyPlanState) -> dict[str, Any]:
        import time

        started_at = time.perf_counter()
        phases = list(state.get("phases") or [])
        tasks = list(state.get("tasks") or [])
        subjects = dict(state.get("subject_checklist") or {})
        total_weeks = int(state.get("total_weeks") or 0)
        reflection = self._reflect_study_plan(
            phases=phases,
            tasks=tasks,
            subjects=subjects,
            total_weeks=total_weeks,
        )
        self._record_trace(state, "reflect_plan", {
            "agent": "StudyPlanAgent",
            "skill": "reflection",
            "status": reflection["status"],
            "missing_items": reflection["missing_items"],
            "next_action": reflection["next_action"],
            "phase_count": len(phases),
            "task_count": len(tasks),
        })

        return {"reflection": reflection}

    def _node_validate_plan(self, state: StudyPlanState) -> dict[str, Any]:
        import time

        started_at = time.perf_counter()
        validation = self._validate_study_plan(
            phases=list(state.get("phases") or []),
            tasks=list(state.get("tasks") or []),
            subjects=dict(state.get("subject_checklist") or {}),
            total_weeks=int(state.get("total_weeks") or 0),
        )
        self._record_trace(state, "validate_plan", {
            "agent": "StudyPlanAgent",
            "skill": "artifact_validation",
            "status": validation["status"],
            "issue_count": len(validation["issues"]),
            "passed": validation["passed"],
        })

        return {
            "validation": validation,
            "status": validation["status"],
        }

    # ?? helpers ???????????????????????????????????????????????????

    def _record_trace(
        self, state: StudyPlanState, node: str, payload: dict[str, Any]
    ) -> None:
        import time
        trace = state.setdefault("trace", [])
        entry = {
            "node": node,
            "ts": time.time(),
            "payload": payload,
        }
        entry.update(self._trace_context(node))
        trace.append(entry)

    def _trace_context(self, node: str) -> dict[str, Any]:
        mapping = {
            "analyze_profile": {
                "agent": "StudyPlanAgent",
                "skill": "analyze_exam_subjects",
                "tool": "StudyPlanSkill",
                "backend": "Profile and recommendation analysis",
            },
            "plan_phases": {
                "agent": "StudyPlanAgent",
                "skill": "generate_phase_schedule",
                "tool": "StudyPlanSkill",
                "backend": "Phase allocation and timeline planning",
            },
            "generate_subjects": {
                "agent": "StudyPlanAgent",
                "skill": "build_subject_checklist",
                "tool": "StudyPlanSkill",
                "backend": "Subject coverage and hour allocation",
            },
            "schedule_tasks": {
                "agent": "StudyPlanAgent",
                "skill": "daily_task_scheduling",
                "tool": "StudyPlanSkill",
                "backend": "Daily practice/task generation",
            },
            "compose_plan": {
                "agent": "StudyPlanAgent",
                "skill": "artifact_composition",
                "tool": "ChatService",
                "backend": "Markdown + optional LLM polish",
            },
            "reflect_plan": {
                "agent": "StudyPlanAgent",
                "skill": "reflection",
                "tool": "StudyPlanValidator",
                "backend": "Feasibility and coverage review",
            },
            "validate_plan": {
                "agent": "StudyPlanAgent",
                "skill": "artifact_validation",
                "tool": "StudyPlanValidator",
                "backend": "Time consistency and task coverage check",
            },
        }
        return mapping.get(node, {"agent": "StudyPlanAgent"})

    def _reflect_study_plan(
        self,
        *,
        phases: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        subjects: dict[str, Any],
        total_weeks: int,
    ) -> dict[str, Any]:
        missing_items: list[str] = []
        if not phases:
            missing_items.append("phases")
        if not tasks:
            missing_items.append("tasks")
        if not subjects:
            missing_items.append("subject_checklist")
        status = "needs_revision" if missing_items else "ok"
        return {
            "status": status,
            "missing_items": missing_items,
            "next_action": "补齐阶段/任务/科目映射" if missing_items else "交给 validator 做硬约束检查",
            "total_weeks": total_weeks,
        }

    def _validate_study_plan(
        self,
        *,
        phases: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        subjects: dict[str, Any],
        total_weeks: int,
    ) -> dict[str, Any]:
        issues: list[str] = []
        if not phases:
            issues.append("phases_empty")
        if not tasks:
            issues.append("tasks_empty")
        if not subjects:
            issues.append("subjects_empty")
        if total_weeks <= 0:
            issues.append("total_weeks_invalid")
        passed = not issues
        return {
            "status": "completed" if passed else "partial",
            "passed": passed,
            "issues": issues,
            "reason": "study plan validation passed" if passed else "study plan validation failed",
        }
