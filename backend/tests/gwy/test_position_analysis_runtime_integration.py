from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.gwy.services.position_analysis_service import PositionAnalysisService


def _snapshot_row():
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        title="测试岗位快照",
        source_sheet="positions",
        filters_json={"year": 2026, "exam_type": "national"},
        snapshot_json={},
        selected_position_ids=[],
        visible_columns=[],
        notes="",
        created_at=None,
    )


def _task_row(snapshot_id):
    return SimpleNamespace(id=uuid4(), snapshot_id=snapshot_id)


class FakeRuntimeService:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or {
            "status": "completed",
            "stage": "position_snapshot_runtime",
            "report": "# Runtime 报告",
            "trace": [{"event": "Stop", "step": "agent_loop", "status": "done"}],
            "output_json": {"runtime_state": {}},
            "recommendations": [],
        }
        self.error = error
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class FakeLegacyAgent:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "completed",
            "stage": "persist_result",
            "report": "# Legacy 报告",
            "trace": [{"step": "legacy", "status": "done"}],
            "output_json": {},
        }


def test_position_analysis_prefers_snapshot_runtime() -> None:
    runtime = FakeRuntimeService()
    legacy = FakeLegacyAgent()
    snapshot = _snapshot_row()
    task = _task_row(snapshot.id)
    service = PositionAnalysisService(
        session=None,
        agent=legacy,
        snapshot_runtime_service_factory=lambda **kwargs: runtime,
        feishu_push_agent=None,
    )

    result = service._run_agent_analysis(
        snapshot_row=snapshot,
        task_row=task,
        user_uuid=snapshot.user_id,
        user_profile={"major": "法学"},
        recommendation_context={"year": 2026, "recommendations": []},
    )

    assert result["report"] == "# Runtime 报告"
    assert runtime.calls
    assert runtime.calls[0]["snapshot"]["title"] == "测试岗位快照"
    assert not legacy.calls


def test_position_analysis_falls_back_when_snapshot_runtime_fails() -> None:
    runtime = FakeRuntimeService(error=RuntimeError("runtime down"))
    legacy = FakeLegacyAgent()
    snapshot = _snapshot_row()
    task = _task_row(snapshot.id)
    service = PositionAnalysisService(
        session=None,
        agent=legacy,
        snapshot_runtime_service_factory=lambda **kwargs: runtime,
        feishu_push_agent=None,
    )

    result = service._run_agent_analysis(
        snapshot_row=snapshot,
        task_row=task,
        user_uuid=snapshot.user_id,
        user_profile={"major": "法学"},
        recommendation_context={"year": 2026, "recommendations": []},
    )

    assert result["report"] == "# Legacy 报告"
    assert legacy.calls
    assert result["trace"][0]["step"] == "snapshot_runtime_fallback"
