from __future__ import annotations

from app.gwy.agent_runtime import ToolContext
from app.gwy.services.position_snapshot_runtime_service import (
    PositionSnapshotRuntimeService,
)


class DecisionAwareReport:
    def run(self, **kwargs):
        assert kwargs["decision_matrix"] == {"items": []}
        assert kwargs["evidence_inventory"] == {"missing": []}
        return {"report": "## Direct conclusion\nPrimary", "report_meta": {}}


def test_compose_report_passes_decision_context_and_returns_contract() -> None:
    service = PositionSnapshotRuntimeService(
        session=None,
        report_generator_agent=DecisionAwareReport(),
    )
    context = ToolContext(
        state={
            "snapshot": {"title": "test"},
            "recommendations": [{"position_id": "p1"}],
            "risk_review": {"risk_items": []},
            "decision_matrix": {"items": []},
            "evidence_inventory": {"missing": []},
        }
    )

    result = service._tool_compose_snapshot_report({}, context)

    assert result["status"] in {"complete", "partial"}
    assert result["decision_matrix"] == {"items": []}
