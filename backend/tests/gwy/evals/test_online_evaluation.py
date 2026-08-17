from app.gwy.evals.online import evaluate_online_observation
from app.gwy.evals.schemas import AgentObservation, EvalCase


def test_online_evaluation_scores_complete_trace_and_business_output() -> None:
    case = EvalCase(
        case_id="online-1",
        task_type="job_filter",
        query="推荐岗位",
        profile={"political_status": "群众"},
        expected={"forbidden_job_ids": ["bad"]},
    )
    observation = AgentObservation(
        final_answer="已完成",
        returned_job_ids=["bad"],
        returned_jobs=[
            {"id": "bad", "political_status_requirement": "中共党员"}
        ],
        trace=[
            {"event": "UserPromptSubmit"},
            {"event": "ToolUse", "tool": "search_positions_pg"},
            {"event": "Stop"},
        ],
        agent_steps=3,
    )

    report = evaluate_online_observation(case, observation)

    assert report["status"] == "failed"
    assert report["trace_complete"] is True
    assert report["scores"]["job_constraint"]["passed"] is False
    assert report["scores"]["efficiency"]["metrics"]["agent_steps"] == 3


def test_online_evaluation_exposes_critical_gate_and_quality_overview() -> None:
    case = EvalCase(
        case_id="online-2",
        task_type="policy_qa",
        query="政策问答",
    )
    observation = AgentObservation(
        final_answer="该政策有效。",
        citations=[{"doc_id": "doc-1", "source_type": "official"}],
        trace=[{"event": "Stop"}],
    )

    report = evaluate_online_observation(case, observation)

    assert report["status"] == "passed"
    assert report["critical_gate"]["passed"] is True
    assert report["quality_overview"]["answer"]["completeness"] == 1.0
