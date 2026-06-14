from __future__ import annotations

from uuid import uuid4

from app.gwy.services.study_plan_service import StudyPlanService


def test_study_plan_service_accepts_position_analysis_task_id(db_session, user) -> None:
    service = StudyPlanService(session=db_session)
    task_id = uuid4()

    result = service.generate(
        user_id=user.id,
        user_profile={
            "major": "计算机技术",
            "education": "本科",
            "daily_study_hours": 4,
        },
        recommendations=[
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "job_title": "岗位A",
                "department_name": "部门A",
            }
        ],
        task_id=task_id,
        exam_type="national",
        exam_year=2026,
        study_hours_per_day=4,
        push_to_feishu=False,
    )

    assert result["plan"]["task_id"] == str(task_id)
    assert result["markdown"]
