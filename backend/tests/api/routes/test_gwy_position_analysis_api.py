from __future__ import annotations

import time
from typing import Any

from app.gwy.services import position_analysis_service as position_analysis_service_module


def _sample_snapshot_payload() -> dict[str, Any]:
    return {
        "title": "北京岗位分析快照",
        "source_sheet": "Sheet1",
        "filters_json": {"year": 2026, "major": "计算机类"},
        "snapshot_json": {
            "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
            "visible_columns": ["department_name", "job_title", "work_location"],
            "notes": "优先北京岗位",
        },
        "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
        "visible_columns": ["department_name", "job_title", "work_location"],
        "notes": "优先北京岗位",
    }


def test_position_analysis_task_api_returns_report_and_persists_snapshot(
    client,
    normal_user_token_headers,
    monkeypatch,
) -> None:
    class FakeStudyPlanService:
        seen_task_id = None

        def __init__(self, session) -> None:
            self.session = session

        def generate(
            self,
            *,
            user_id,
            user_profile,
            recommendations,
            task_id=None,
            exam_type="national",
            exam_year=None,
            study_hours_per_day=4,
            push_to_feishu=False,
        ) -> dict[str, Any]:
            _ = (
                self.session,
                user_id,
                user_profile,
                recommendations,
                exam_type,
                exam_year,
                study_hours_per_day,
                push_to_feishu,
            )
            FakeStudyPlanService.seen_task_id = task_id
            return {
                "plan": {
                    "id": "plan-1",
                    "title": "2026 年复习规划",
                    "exam_type": "national",
                    "exam_year": 2026,
                    "status": "completed",
                },
                "phases": [
                    {
                        "id": "phase-1",
                        "phase_order": 1,
                        "phase_name": "基础阶段",
                        "phase_goal": "夯实基础",
                        "week_start": 1,
                        "week_end": 4,
                        "focus_subjects": ["行测"],
                        "study_hours_per_day": 4,
                    }
                ],
                "subjects": [
                    {
                        "id": "subject-1",
                        "subject_name": "行测",
                        "subject_category": "笔试",
                        "weight_percent": 50,
                        "total_hours": 120,
                        "checklist_items": ["完成基础模块"],
                        "resources": ["题库"],
                    }
                ],
                "tasks": [
                    {
                        "id": "task-item-1",
                        "week_number": 1,
                        "day_of_week": 1,
                        "subject": "行测",
                        "task_title": "基础练习",
                        "task_description": "基础练习",
                        "estimated_minutes": 60,
                        "priority": 1,
                        "completed": False,
                    }
                ],
                "markdown": "# 2026 年复习规划\n\n## 基础阶段",
            }

    monkeypatch.setattr(
        position_analysis_service_module,
        "StudyPlanService",
        FakeStudyPlanService,
    )

    response = client.post(
        "/api/v1/gwy/analysis/tasks",
        json={
            "snapshot": _sample_snapshot_payload(),
            "title": "北京岗位筛选分析",
        },
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["task"]["stage"] == "queued"
    assert payload["report"] is None
    assert payload["trace"] == []

    task_id = payload["task"]["id"]
    snapshot_id = payload["snapshot"]["id"]

    task_payload = None
    for _ in range(30):
        task_response = client.get(
            f"/api/v1/gwy/analysis/tasks/{task_id}",
            headers=normal_user_token_headers,
        )
        assert task_response.status_code == 200
        task_payload = task_response.json()
        if task_payload["status"] != "running":
            break
        time.sleep(0.2)

    assert task_payload is not None
    assert task_payload["status"] in {"completed", "needs_more_info"}
    assert task_payload["stage"] in {"persist_result", "clarify_requirements"}
    assert str(FakeStudyPlanService.seen_task_id) == task_id
    assert task_payload["output_json"]["study_plan"]["plan"]["title"] == "2026 年复习规划"
    assert task_payload["output_json"]["study_plan"]["markdown"].startswith(
        "# 2026 年复习规划"
    )
    assert task_payload["id"] == task_id
    assert task_payload["report_text"].startswith("#")

    trace_response = client.get(
        f"/api/v1/gwy/analysis/tasks/{task_id}/trace",
        headers=normal_user_token_headers,
    )
    assert trace_response.status_code == 200
    assert trace_response.json()["trace"][0]["step"] == "load_snapshot"

    report_response = client.get(
        f"/api/v1/gwy/analysis/tasks/{task_id}/report",
        headers=normal_user_token_headers,
    )
    assert report_response.status_code == 200
    assert report_response.json()["report"] == task_payload["report_text"]

    snapshot_response = client.get(
        f"/api/v1/gwy/analysis/snapshots/{snapshot_id}",
        headers=normal_user_token_headers,
    )
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["id"] == snapshot_id


def test_position_analysis_task_api_handles_memory_context_failure(
    client,
    normal_user_token_headers,
    monkeypatch,
) -> None:
    class FakeStudyPlanService:
        def __init__(self, session) -> None:
            self.session = session

        def generate(
            self,
            *,
            user_id,
            user_profile,
            recommendations,
            task_id=None,
            exam_type="national",
            exam_year=None,
            study_hours_per_day=4,
            push_to_feishu=False,
        ) -> dict[str, Any]:
            _ = (
                self.session,
                user_id,
                user_profile,
                recommendations,
                task_id,
                exam_type,
                exam_year,
                study_hours_per_day,
                push_to_feishu,
            )
            return {
                "plan": {
                    "id": "plan-2",
                    "title": "2026 年复习规划",
                    "exam_type": "national",
                    "exam_year": 2026,
                    "status": "completed",
                },
                "phases": [],
                "subjects": [],
                "tasks": [],
                "markdown": "# 2026 年复习规划",
            }

    class BrokenAgentMemoryService:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def save_task_context(self, payload) -> None:
            _ = payload
            raise RuntimeError("memory context unavailable")

        def build_memory_prompt(self):
            raise RuntimeError("memory prompt unavailable")

    monkeypatch.setattr(
        position_analysis_service_module,
        "StudyPlanService",
        FakeStudyPlanService,
    )
    monkeypatch.setattr(
        position_analysis_service_module,
        "AgentMemoryService",
        BrokenAgentMemoryService,
    )

    response = client.post(
        "/api/v1/gwy/analysis/tasks",
        json={
            "snapshot": _sample_snapshot_payload(),
            "title": "北京岗位筛选分析",
        },
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    task_id = response.json()["task"]["id"]

    task_payload = None
    for _ in range(30):
        task_response = client.get(
            f"/api/v1/gwy/analysis/tasks/{task_id}",
            headers=normal_user_token_headers,
        )
        assert task_response.status_code == 200
        task_payload = task_response.json()
        if task_payload["status"] != "running":
            break
        time.sleep(0.2)

    assert task_payload is not None
    assert task_payload["status"] in {"completed", "needs_more_info"}


def test_position_analysis_task_api_marks_failed_when_analysis_raises(
    client,
    normal_user_token_headers,
    monkeypatch,
) -> None:
    class BrokenPositionAnalysisService:
        def __init__(self, session, chat_service) -> None:
            _ = (session, chat_service)

        def execute_existing_task(self, *, snapshot_id, task_id, user_id):
            _ = (snapshot_id, task_id, user_id)
            raise RuntimeError("analysis exploded")

    monkeypatch.setattr(
        position_analysis_service_module,
        "PositionAnalysisService",
        BrokenPositionAnalysisService,
    )

    response = client.post(
        "/api/v1/gwy/analysis/tasks",
        json={
            "snapshot": _sample_snapshot_payload(),
            "title": "北京岗位筛选分析",
        },
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    task_id = response.json()["task"]["id"]

    task_payload = None
    for _ in range(30):
        task_response = client.get(
            f"/api/v1/gwy/analysis/tasks/{task_id}",
            headers=normal_user_token_headers,
        )
        assert task_response.status_code == 200
        task_payload = task_response.json()
        if task_payload["status"] != "running":
            break
        time.sleep(0.2)

    assert task_payload is not None
    assert task_payload["status"] == "failed"
    assert task_payload["stage"] == "failed"
    assert task_payload["error_message"] == "analysis exploded"
