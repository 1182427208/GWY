"""Tests for study plan generation."""

from __future__ import annotations

from uuid import uuid4

from app.gwy.agents.study_plan_agent import StudyPlanAgent
from app.gwy.skills.study_plan_skills import (
    analyze_exam_subjects,
    build_subject_checklist,
    estimate_exam_date,
    format_study_plan_markdown,
    generate_phase_schedule,
)


class TestStudyPlanSkills:

    def test_analyze_exam_subjects_default(self) -> None:
        result = analyze_exam_subjects(
            recommendations=[],
            user_profile={},
            exam_type="国考",
        )
        subjects = result.get("subjects", {})
        assert "行测" in subjects
        assert "申论" in subjects
        assert subjects["行测"]["weight"] == 50
        assert subjects["申论"]["weight"] == 50

    def test_analyze_exam_subjects_with_professional(self) -> None:
        result = analyze_exam_subjects(
            recommendations=[{"exam_category": "专业科目考试"}],
            user_profile={},
        )
        subjects = result.get("subjects", {})
        assert "专业科目" in subjects
        assert subjects["专业科目"]["weight"] == 20

    def test_estimate_exam_date(self) -> None:
        date = estimate_exam_date(exam_year=2025)
        assert date.year == 2025
        assert date.month == 11
        assert date.weekday() == 6

    def test_generate_phase_schedule_3_phases(self) -> None:
        import datetime
        exam_date = datetime.date(2025, 11, 30)
        start_date = datetime.date(2025, 8, 1)
        phases = generate_phase_schedule(
            exam_date=exam_date,
            start_date=start_date,
            study_hours_per_day=4,
        )
        assert len(phases) == 3
        assert phases[0]["phase_name"] == "基础期"
        assert phases[1]["phase_name"] == "强化期"
        assert phases[2]["phase_name"] == "冲刺期"

    def test_build_subject_checklist(self) -> None:
        subjects = {
            "行测": {
                "category": "行测",
                "modules": {"模块1": ["子项A", "子项B"]},
                "weight": 50,
            },
            "申论": {
                "category": "申论",
                "modules": {"模块2": ["子项C"]},
                "weight": 50,
            },
        }
        checklist = build_subject_checklist(subjects=subjects)
        assert "行测" in checklist
        assert len(checklist["行测"]["checklist_items"]) >= 2

    def test_format_study_plan_markdown(self) -> None:
        markdown = format_study_plan_markdown(
            title="2026 Exam Plan",
            study_plan={
                "estimated_exam_date": "2025-11-30",
                "study_hours_per_day": 4,
                "total_weeks": 12,
            },
            phases=[
                {
                    "phase_name": "Phase1",
                    "week_start": 1,
                    "week_end": 4,
                    "phase_goal": "Foundations",
                    "study_hours_per_day": 4,
                    "focus_subjects": ["Subject A"],
                }
            ],
            subjects={
                "Subject A": {
                    "subject_category": "CatA",
                    "weight_percent": 50,
                    "checklist_items": ["Module1: Topic1"],
                    "resources": ["Resource1"],
                }
            },
            tasks=[
                {
                    "week_number": 1,
                    "day_of_week": 1,
                    "subject": "Subject A",
                    "task_title": "Practice 1",
                    "estimated_minutes": 60,
                }
            ],
        )
        assert "2026 Exam Plan" in markdown
        assert "Phase1" in markdown
        assert "Practice 1" in markdown


class TestStudyPlanAgent:

    def test_agent_run_returns_completed(self) -> None:
        agent = StudyPlanAgent()
        result = agent.run(
            user_profile={
                "education": "本科",
                "major": "法学",
                "target_regions": ["北京"],
            },
            recommendations=[
                {
                    "id": str(uuid4()),
                    "department_name": "Department X",
                    "job_title": "Position Y",
                    "exam_category": "General",
                }
            ],
            exam_type="国考",
            exam_year=2025,
            study_hours_per_day=4,
        )
        assert result["status"] == "completed"
        assert "plan_markdown" in result
        assert "plan_title" in result
        assert len(result.get("phases", [])) == 3
        assert len(result.get("tasks", [])) > 0
