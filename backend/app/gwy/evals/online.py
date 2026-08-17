from __future__ import annotations

from typing import Any

from app.gwy.evals.aggregation import build_case_report
from app.gwy.evals.run_eval import score_case
from app.gwy.evals.schemas import AgentObservation, EvalCase


def evaluate_online_observation(
    case: EvalCase,
    observation: AgentObservation,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    scores = score_case(case, observation, top_k=top_k)
    trace_complete = _trace_complete(observation.trace, observation.status)
    report = build_case_report(
        observation=observation,
        scores=scores,
        trace_complete=trace_complete,
    )
    failures = list(report["failure_reasons"])
    if not trace_complete:
        failures.append("agent trace did not reach a terminal event")
    report["failure_reasons"] = failures
    report["trace_complete"] = trace_complete
    report["status"] = (
        "passed"
        if report["status"] == "passed" and trace_complete
        else ("blocked" if observation.status == "error" else "failed")
    )
    report["observation"] = observation.model_dump()
    return report


def _trace_complete(trace: list[dict[str, Any]], status: str) -> bool:
    if status == "error" or not trace:
        return False
    return any(
        str(item.get("event") or "") in {"Stop", "done", "Finalize"}
        or str(item.get("step") or "") == "finalize"
        and str(item.get("status") or "") == "done"
        for item in trace
    )
