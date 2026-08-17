from __future__ import annotations

from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


def score_task_success(case: EvalCase, observation: AgentObservation) -> ScoreBundle:
    failures: list[str] = []
    if observation.status == "error":
        error = observation.raw_output.get("error")
        failures.append(f"agent runner failed: {error or 'unknown error'}")
    if (
        case.expected.expected_final_status
        and observation.status != case.expected.expected_final_status
    ):
        failures.append(
            f"status {observation.status!r} != expected {case.expected.expected_final_status!r}"
        )
    if case.expected.report_required and not observation.final_answer.strip():
        failures.append("report/final answer is required")
    if case.expected.should_ask_clarification:
        markers = ("?", "？", "请提供", "需要补充", "还需要")
        if not observation.raw_output.get("need_more_info") and not any(
            marker in observation.final_answer for marker in markers
        ):
            failures.append("expected clarification request")
    if case.expected.feishu_required and not _feishu_push_succeeded(observation):
        failures.append("Feishu push result is required")
    return ScoreBundle(
        name="task_success",
        passed=not failures,
        metrics={"success": 0.0 if failures else 1.0},
        failure_reasons=failures,
    )


def _feishu_push_succeeded(observation: AgentObservation) -> bool:
    metadata = observation.raw_output.get("metadata_json") or {}
    for payload in (observation.raw_output, metadata):
        result = payload.get("feishu_push") or payload.get("feishu")
        if isinstance(result, dict) and str(result.get("status") or "") in {
            "done",
            "sent",
            "success",
        }:
            return True
    return any(
        call.tool in {"send_feishu_message", "push_feishu_report"} and call.success
        for call in observation.tool_calls
    )
