from __future__ import annotations

import json

from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
from app.gwy.agents.study_plan_agent import StudyPlanAgent


class FakeStudyChat:
    def chat_completion(self, messages, temperature=0.3):  # noqa: ANN001
        return json.dumps(
            {
                "title": "2026 公务员考试学习计划",
                "study_tips": ["先补基础，再刷题"],
            },
            ensure_ascii=False,
        )


def test_report_generator_trace_includes_agent_and_skill_context() -> None:
    agent = ReportGeneratorAgent(chat_service=None)

    result = agent.run(
        title="岗位分析报告",
        recommendations=[
            {"department_name": "A局", "job_title": "综合管理", "risk_level": "low"},
        ],
        risk_review={"risk_level": "low", "risk_items": []},
        decision_matrix={"matrix": []},
        evidence_inventory={"items": []},
        verification_tasks=["核对学历条件"],
    )

    trace = result["trace"]
    plan_entry = next(item for item in trace if item["step"] == "plan")
    draft_entry = next(item for item in trace if item["step"] == "draft_report")
    reflect_entry = next(item for item in trace if item["step"] == "reflect")
    validate_entry = next(item for item in trace if item["step"] == "validate")

    assert plan_entry["agent"] == "ReportGeneratorAgent"
    assert plan_entry["skill"] == "report_outline_planning"
    assert draft_entry["tool"] == "ArtifactComposer"
    assert reflect_entry["skill"] == "reflection"
    assert validate_entry["skill"] == "artifact_validation"


def test_study_plan_trace_includes_agent_and_skill_context() -> None:
    agent = StudyPlanAgent(chat_service=FakeStudyChat())

    result = agent.run(
        user_profile={
            "education": "本科",
            "major": "法学",
            "target_regions": ["北京"],
        },
        recommendations=[
            {"department_name": "A局", "job_title": "综合管理"},
        ],
        exam_type="国考",
        exam_year=2026,
        study_hours_per_day=4,
    )

    trace = result["trace"]
    analyze_entry = next(item for item in trace if item["node"] == "analyze_profile")
    compose_entry = next(item for item in trace if item["node"] == "compose_plan")
    reflect_entry = next(item for item in trace if item["node"] == "reflect_plan")
    validate_entry = next(item for item in trace if item["node"] == "validate_plan")

    assert analyze_entry["agent"] == "StudyPlanAgent"
    assert analyze_entry["skill"] == "analyze_exam_subjects"
    assert analyze_entry["payload"]["subjects"]
    assert compose_entry["skill"] == "artifact_composition"
    assert compose_entry["payload"]["status"] == "completed"
    assert reflect_entry["skill"] == "reflection"
    assert validate_entry["skill"] == "artifact_validation"
