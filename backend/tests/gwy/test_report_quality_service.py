from __future__ import annotations

from app.gwy.services.report_quality_service import ReportQualityService


def test_quality_rejects_report_without_decision_layers_and_actions() -> None:
    result = ReportQualityService().validate(
        report="# Position Report\n\n- 15 candidates\n- Please review manually.",
        decision_matrix={
            "items": [
                {
                    "position_id": "p1",
                    "tier": "primary",
                    "verification_tasks": ["Check official notice"],
                }
            ]
        },
        risk_review={"risk_items": []},
    )

    assert result["passed"] is False
    assert "tier" in result["missing_requirements"]
    assert "comparison" in result["missing_requirements"]


def test_quality_accepts_ranked_report_with_comparison_and_actions() -> None:
    result = ReportQualityService().validate(
        report=(
            "# Position Report\n\n"
            "## Direct conclusion\nPrimary: Position A\n"
            "## Position tiers\nPrimary / Backup\n"
            "## Comparison\nPosition A is more suitable than Position B.\n"
            "## Verification checklist\nCheck official notice."
        ),
        decision_matrix={
            "items": [
                {
                    "position_id": "p1",
                    "tier": "primary",
                    "verification_tasks": ["Check official notice"],
                }
            ]
        },
        risk_review={"risk_items": []},
    )

    assert result["passed"] is True
