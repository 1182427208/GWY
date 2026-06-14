"""Study plan generation service: orchestrates StudyPlanAgent + persistence + Feishu push."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.gwy.agents.feishu_push_agent import FeishuPushAgent
from app.gwy.agents.study_plan_agent import StudyPlanAgent
from app.gwy.models import (
    GwyStudyPlan,
    GwyStudyPhase,
    GwyStudySubject,
    GwyStudyTask,
)

logger = logging.getLogger(__name__)


class StudyPlanService:

    def __init__(
        self,
        *,
        session: Session,
        agent: StudyPlanAgent | None = None,
        feishu_push_agent: FeishuPushAgent | None = None,
    ) -> None:
        self.session = session
        self.agent = agent or StudyPlanAgent()
        self.feishu_push_agent = feishu_push_agent or FeishuPushAgent()

    def generate(
        self,
        *,
        user_id: UUID,
        user_profile: dict[str, Any],
        recommendations: list[dict[str, Any]],
        task_id: UUID | None = None,
        exam_type: str = "??",
        exam_year: int | None = None,
        study_hours_per_day: int = 4,
        push_to_feishu: bool = False,
    ) -> dict[str, Any]:
        result = self.agent.run(
            user_profile=user_profile,
            recommendations=recommendations,
            exam_type=exam_type,
            exam_year=exam_year,
            study_hours_per_day=study_hours_per_day,
        )
        plan = self._persist(
            user_id=user_id,
            task_id=task_id,
            result=result,
            recommendations=recommendations,
            user_profile=user_profile,
            exam_type=exam_type,
            exam_year=exam_year,
            study_hours_per_day=study_hours_per_day,
        )

        if push_to_feishu:
            self._push_to_feishu(plan)

        return {
            "plan": self._serialize_plan(plan),
            "phases": self._serialize_plan_phases(plan.id),
            "subjects": self._serialize_plan_subjects(plan.id),
            "tasks": self._serialize_plan_tasks(plan.id),
            "markdown": plan.report_markdown,
        }

    def get_plan(self, *, plan_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        plan = self.session.get(GwyStudyPlan, plan_id)
        if plan is None or (plan.user_id and plan.user_id != user_id):
            return None
        return {
            "plan": self._serialize_plan(plan),
            "phases": self._serialize_plan_phases(plan.id),
            "subjects": self._serialize_plan_subjects(plan.id),
            "tasks": self._serialize_plan_tasks(plan.id),
            "markdown": plan.report_markdown,
        }

    def list_plans(self, *, user_id: UUID) -> list[dict[str, Any]]:
        from sqlmodel import select
        stmt = (
            select(GwyStudyPlan)
            .where(GwyStudyPlan.user_id == user_id)
            .order_by(GwyStudyPlan.created_at.desc())
        )
        plans = self.session.exec(stmt).all()
        return [self._serialize_plan(p) for p in plans]

    def delete_plan(self, *, plan_id: UUID, user_id: UUID) -> bool:
        plan = self.session.get(GwyStudyPlan, plan_id)
        if plan is None or (plan.user_id and plan.user_id != user_id):
            return False
        # Delete children
        for model in [GwyStudyPhase, GwyStudyTask, GwyStudySubject]:
            stmt = getattr(model, "study_plan_id") == plan_id
            from sqlmodel import delete
            self.session.exec(delete(model).where(stmt))
        self.session.delete(plan)
        self.session.commit()
        return True

    # -- internal ---------------------------------------------------

    def _persist(
        self,
        *,
        user_id: UUID,
        task_id: UUID | None,
        result: dict[str, Any],
        recommendations: list[dict[str, Any]],
        user_profile: dict[str, Any],
        exam_type: str,
        exam_year: int | None,
        study_hours_per_day: int,
    ) -> GwyStudyPlan:
        import datetime as dt
        from app.gwy.skills.study_plan_skills import estimate_exam_date
        exam_date = estimate_exam_date(exam_year=exam_year)

        position_ids = [str(r.get("id", "")) for r in (recommendations or []) if r.get("id")]
        plan = GwyStudyPlan(
            user_id=user_id,
            task_id=task_id,
            title=result.get("plan_title", "????"),
            exam_type=exam_type,
            exam_year=exam_year,
            estimated_exam_date=dt.datetime.combine(exam_date, dt.time.min),
            study_hours_per_day=study_hours_per_day,
            total_weeks=result.get("total_weeks", 12),
            profile_snapshot=user_profile,
            position_ids=position_ids,
            report_markdown=result.get("plan_markdown", ""),
            status="completed",
        )
        self.session.add(plan)
        self.session.flush()

        # Persist phases
        for phase in result.get("phases", []):
            self.session.add(GwyStudyPhase(
                study_plan_id=plan.id,
                phase_order=phase.get("phase_order", 0),
                phase_name=phase.get("phase_name", ""),
                phase_goal=phase.get("phase_goal"),
                week_start=phase.get("week_start", 1),
                week_end=phase.get("week_end", 4),
                focus_subjects=phase.get("focus_subjects", []),
                study_hours_per_day=phase.get("study_hours_per_day", 4),
            ))

        # Persist subjects
        for name, info in (result.get("subject_checklist", {})).items():
            self.session.add(GwyStudySubject(
                study_plan_id=plan.id,
                subject_name=name,
                subject_category=info.get("subject_category", ""),
                weight_percent=info.get("weight_percent", 0),
                total_hours=info.get("total_hours", 0),
                checklist_items=info.get("checklist_items", []),
                resources=info.get("resources", []),
            ))

        # Persist tasks (first 2 weeks only to keep DB lean)
        for task in (result.get("tasks", []))[:14 * 2]:
            self.session.add(GwyStudyTask(
                study_plan_id=plan.id,
                week_number=task.get("week_number", 1),
                day_of_week=task.get("day_of_week", 1),
                subject=task.get("subject", ""),
                task_title=task.get("task_title", ""),
                task_description=task.get("task_description"),
                estimated_minutes=task.get("estimated_minutes", 60),
                priority=task.get("priority", 1),
                completed=task.get("completed", False),
            ))

        self.session.commit()
        self.session.refresh(plan)
        return plan

    def _push_to_feishu(self, plan: GwyStudyPlan) -> None:
        try:
            self.feishu_push_agent.run(
                report_kind="study_plan",
                title=plan.title or "????",
                report_text=plan.report_markdown or "",
                task_id=str(plan.id),
            )
        except Exception:
            logger.exception("Failed to push study plan to Feishu")

    # -- serialization ----------------------------------------------

    def _serialize_plan(self, plan: GwyStudyPlan) -> dict[str, Any]:
        return {
            "id": str(plan.id),
            "user_id": str(plan.user_id) if plan.user_id else None,
            "task_id": str(plan.task_id) if plan.task_id else None,
            "title": plan.title,
            "exam_type": plan.exam_type,
            "exam_year": plan.exam_year,
            "estimated_exam_date": str(plan.estimated_exam_date) if plan.estimated_exam_date else None,
            "study_hours_per_day": plan.study_hours_per_day,
            "total_weeks": plan.total_weeks,
            "status": plan.status,
            "created_at": str(plan.created_at) if plan.created_at else None,
        }

    def _serialize_plan_phases(self, plan_id: UUID) -> list[dict[str, Any]]:
        from sqlmodel import select
        stmt = select(GwyStudyPhase).where(
            GwyStudyPhase.study_plan_id == plan_id
        ).order_by(GwyStudyPhase.phase_order)
        phases = self.session.exec(stmt).all()
        return [{
            "id": str(p.id),
            "phase_order": p.phase_order,
            "phase_name": p.phase_name,
            "phase_goal": p.phase_goal,
            "week_start": p.week_start,
            "week_end": p.week_end,
            "focus_subjects": p.focus_subjects,
            "study_hours_per_day": p.study_hours_per_day,
        } for p in phases]

    def _serialize_plan_subjects(self, plan_id: UUID) -> list[dict[str, Any]]:
        from sqlmodel import select
        stmt = select(GwyStudySubject).where(GwyStudySubject.study_plan_id == plan_id)
        subjects = self.session.exec(stmt).all()
        return [{
            "id": str(s.id),
            "subject_name": s.subject_name,
            "subject_category": s.subject_category,
            "weight_percent": s.weight_percent,
            "total_hours": s.total_hours,
            "checklist_items": s.checklist_items,
            "resources": s.resources,
        } for s in subjects]

    def _serialize_plan_tasks(self, plan_id: UUID) -> list[dict[str, Any]]:
        from sqlmodel import select
        stmt = select(GwyStudyTask).where(
            GwyStudyTask.study_plan_id == plan_id
        ).order_by(GwyStudyTask.week_number, GwyStudyTask.day_of_week)
        tasks = self.session.exec(stmt).all()
        return [{
            "id": str(t.id),
            "week_number": t.week_number,
            "day_of_week": t.day_of_week,
            "subject": t.subject,
            "task_title": t.task_title,
            "task_description": t.task_description,
            "estimated_minutes": t.estimated_minutes,
            "priority": t.priority,
            "completed": t.completed,
        } for t in tasks]
