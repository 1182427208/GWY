from __future__ import annotations

from uuid import uuid4

from app.gwy.services.autonomous_chat_agent_service import AutonomousChatAgentService


def test_autonomous_position_recommendation_requires_snapshot() -> None:
    service = AutonomousChatAgentService.__new__(AutonomousChatAgentService)

    result = service.run(
        query="帮我推荐几个公务员岗位",
        user_id=uuid4(),
        session_id=uuid4(),
        position_profile={"major": "法学", "education": "本科"},
    )

    assert result["intent"] == "position_snapshot_required"
    assert "固定快照" in result["answer"]
    assert result["recommendations"] == []
    assert result["decision_branch"] == "position_snapshot_gate"


def test_autonomous_position_recommendation_with_snapshot_uses_runtime(monkeypatch) -> None:
    service = AutonomousChatAgentService.__new__(AutonomousChatAgentService)
    service.session = None
    service.chat_service = None
    calls = []

    class FakeSnapshotRuntime:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            return {
                "report": "# 快照岗位报告",
                "trace": [{"event": "Stop", "status": "done"}],
                "recommendations": [{"position_id": "p1"}],
                "risk_review": {"risk_level": "low"},
                "study_plan": {"plan": {"title": "计划"}},
                "needs_more_info": False,
                "missing_fields": [],
            }

    monkeypatch.setattr(
        "app.gwy.services.autonomous_chat_agent_service.PositionSnapshotRuntimeService",
        FakeSnapshotRuntime,
    )

    result = service.run(
        query="帮我推荐几个公务员岗位",
        user_id=uuid4(),
        session_id=uuid4(),
        position_profile={"major": "法学", "education": "本科"},
        snapshot={"title": "固定快照", "selected_position_ids": []},
    )

    assert result["decision_branch"] == "position_snapshot_runtime"
    assert result["answer"] == "# 快照岗位报告"
    assert result["recommendations"] == [{"position_id": "p1"}]
    assert calls[0]["snapshot"]["title"] == "固定快照"
