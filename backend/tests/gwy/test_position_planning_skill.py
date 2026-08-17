from __future__ import annotations

from pathlib import Path


def test_position_planning_skill_matches_runtime_agent_loop_tools() -> None:
    path = (
        Path(__file__).parents[2]
        / "app"
        / "gwy"
        / "runtime_skills"
        / "position-planning"
        / "SKILL.md"
    )
    content = path.read_text(encoding="utf-8")

    for tool_name in (
        "analyze_snapshot_positions",
        "research_position_history",
        "retrieve_position_policy_evidence",
        "verify_position_hidden_requirements",
        "review_position_risks",
        "build_position_decision_matrix",
        "compose_snapshot_report",
        "validate_report_requirements",
    ):
        assert f"`{tool_name}`" in content

    assert "Do not compose a report while required evidence is missing" in content
