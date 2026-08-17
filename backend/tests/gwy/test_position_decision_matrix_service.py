from __future__ import annotations

from app.gwy.services.position_decision_matrix_service import (
    PositionDecisionMatrixService,
)


def test_matrix_excludes_hard_condition_failures() -> None:
    result = PositionDecisionMatrixService().build(
        recommendations=[
            {
                "position_id": "p1",
                "job_title": "Position A",
                "score": 90,
                "hard_filter_passed": False,
                "hard_filter_reasons": ["major mismatch"],
                "risks": [],
            }
        ],
        research=[],
        risk_review={"risk_items": []},
        profile={"major": "Law"},
    )

    item = result["items"][0]
    assert item["tier"] == "exclude"
    assert item["fit_score"] == 0
    assert "major mismatch" in item["reasons"]


def test_matrix_marks_missing_competition_data_and_creates_follow_up() -> None:
    result = PositionDecisionMatrixService().build(
        recommendations=[
            {
                "position_id": "p2",
                "job_title": "Position B",
                "score": 82,
                "hard_filter_passed": True,
                "reasons": [{"text": "major match"}],
                "risks": [],
            }
        ],
        research=[
            {
                "position_id": "p2",
                "history": {"records": [], "summary": {}},
                "web_results": [],
            }
        ],
        risk_review={"risk_items": []},
        profile={"major": "Law"},
    )

    item = result["items"][0]
    assert item["tier"] in {"primary", "caution"}
    assert item["confidence"] == "low"
    assert "competition" in item["unknowns"]
    assert item["verification_tasks"]
    assert result["missing"]
