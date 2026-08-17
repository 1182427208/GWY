from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.gwy.evals.schemas import AgentObservation, CaseResult, ScoreBundle

_NON_CRITICAL_SCORE_NAMES = {"efficiency"}


def build_case_report(
    *,
    observation: AgentObservation,
    scores: list[ScoreBundle],
    trace_complete: bool,
) -> dict[str, Any]:
    score_cards = {score.name: _score_payload(score) for score in scores}
    failure_reasons = [
        reason for score in scores for reason in score.failure_reasons
    ]
    critical_failures = [
        score.name
        for score in scores
        if score.name not in _NON_CRITICAL_SCORE_NAMES and not score.passed
    ]
    blocked = observation.status == "error"
    critical_gate_passed = trace_complete and not critical_failures and not blocked
    status = "blocked" if blocked else ("passed" if critical_gate_passed else "failed")
    quality_overview = _case_quality_overview(score_cards, observation)
    execution_quality = score_cards.get("efficiency", {}).get("metrics", {})
    return {
        "status": status,
        "critical_gate": {
            "passed": critical_gate_passed,
            "blocked": blocked,
            "trace_complete": trace_complete,
            "failed_scores": critical_failures,
            "failure_reasons": failure_reasons,
        },
        "quality_overview": quality_overview,
        "execution_quality": execution_quality,
        "score_cards": score_cards,
        "scores": score_cards,
        "failure_reasons": failure_reasons,
    }


def aggregate_run_results(
    results: list[CaseResult],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_count = len(results)
    passed_count = sum(1 for result in results if result.passed)
    failed_count = case_count - passed_count
    blocked_count = sum(
        1 for result in results if str(result.observation.status) == "error"
    )
    metric_totals: dict[str, list[float]] = defaultdict(list)
    score_cards: dict[str, dict[str, Any]] = {}
    failure_taxonomy = Counter()

    for result in results:
        for score in result.scores:
            card = score_cards.setdefault(
                score.name,
                {"case_count": 0, "passed_count": 0, "metrics": {}, "failure_reasons": Counter()},
            )
            card["case_count"] += 1
            card["passed_count"] += 1 if score.passed else 0
            for name, value in score.metrics.items():
                if isinstance(value, (int, float)):
                    metric_totals[f"{score.name}.{name}"].append(float(value))
            for reason in score.failure_reasons:
                card["failure_reasons"][reason] += 1
                failure_taxonomy[_classify_failure(reason)] += 1

    for name, card in score_cards.items():
        counts = card["case_count"] or 1
        card["pass_rate"] = card["passed_count"] / counts
        card["metrics"] = {
            metric_name: sum(values) / len(values)
            for metric_name, values in sorted(
                (
                    (key.split(".", 1)[1], values)
                    for key, values in metric_totals.items()
                    if key.startswith(f"{name}.")
                ),
                key=lambda item: item[0],
            )
            if values
        }
        card["failure_reasons"] = dict(card["failure_reasons"])

    quality_overview = {
        "task": {
            "completion_rate": _average_metric(results, "task_success", "success"),
            "position_identity_accuracy": _average_metric(
                results, "position_identity", "position_identity_accuracy"
            ),
            "job_f1": _average_metric(results, "job_constraint", "job_f1"),
            "tool_f1": _average_metric(results, "tool_call", "tool_f1"),
            "evidence_coverage": _average_metric(
                results, "evidence_quality", "evidence_coverage"
            ),
            "claim_groundedness": _average_metric(
                results, "claim_groundedness", "claim_groundedness"
            ),
            "answer_completeness": _average_metric(
                results, "answer_quality", "completeness"
            ),
        },
        "execution": {
            "tool_calls": _average_metric(results, "efficiency", "tool_call_count"),
            "agent_turns": _average_metric(results, "efficiency", "agent_steps"),
            "latency_ms": _average_metric(results, "efficiency", "latency_ms"),
            "input_tokens": _average_metric(results, "efficiency", "input_tokens"),
            "output_tokens": _average_metric(results, "efficiency", "output_tokens"),
            "estimated_cost": _average_metric(
                results, "efficiency", "estimated_cost"
            ),
        },
    }
    critical_gate = {
        "passed_rate": (
            sum(1 for result in results if _critical_passed(result)) / case_count
            if case_count
            else 0.0
        ),
        "passed_count": sum(1 for result in results if _critical_passed(result)),
        "failed_count": sum(1 for result in results if not _critical_passed(result)),
        "blocked_count": blocked_count,
    }
    overall_status = _overall_status(results)
    flat_metrics = {
        metric_name: sum(values) / len(values)
        for metric_name, values in sorted(metric_totals.items())
        if values
    }
    return {
        "overall_status": overall_status,
        "experiment_name": config.get("experiment_name") if config else None,
        "dataset_split": config.get("dataset_split") if config else None,
        "experiment_id": config.get("experiment_name") if config else None,
        "dataset_version": config.get("dataset_version") if config else None,
        "model": config.get("model") if config else None,
        "prompt_version": config.get("prompt_version") if config else None,
        "knowledge_version": config.get("knowledge_version") if config else None,
        "job_table_version": config.get("job_table_version") if config else None,
        "git_commit": config.get("git_commit") if config else None,
        "case_count": case_count,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "blocked_count": blocked_count,
        "task_success_rate": passed_count / case_count if case_count else 0.0,
        "critical_gate": critical_gate,
        "quality_overview": quality_overview,
        "score_cards": score_cards,
        "metrics": flat_metrics,
        "failure_taxonomy": dict(failure_taxonomy),
        "config": config or {},
    }


def _score_payload(score: ScoreBundle) -> dict[str, Any]:
    return {
        "passed": score.passed,
        "metrics": score.metrics,
        "failure_reasons": score.failure_reasons,
        "details": score.details,
    }


def _average_metric(
    results: list[CaseResult], score_name: str, metric_name: str
) -> float | None:
    values: list[float] = []
    for result in results:
        for score in result.scores:
            if score.name != score_name:
                continue
            value = score.metrics.get(metric_name)
            if isinstance(value, (int, float)):
                values.append(float(value))
    if not values:
        return None
    return sum(values) / len(values)


def _critical_passed(result: CaseResult) -> bool:
    return result.observation.status != "error" and all(
        score.passed for score in result.scores if score.name not in _NON_CRITICAL_SCORE_NAMES
    )


def _overall_status(results: list[CaseResult]) -> str:
    if not results:
        return "BLOCKED"
    if all(_critical_passed(result) for result in results):
        return "PASS"
    if any(result.observation.status == "error" for result in results):
        return "BLOCKED" if not any(_critical_passed(result) for result in results) else "PARTIAL"
    passed_count = sum(1 for result in results if _critical_passed(result))
    if passed_count == 0:
        return "FAIL"
    if passed_count == len(results):
        return "PASS"
    return "PARTIAL"


def _case_quality_overview(
    score_cards: dict[str, dict[str, Any]], observation: AgentObservation
) -> dict[str, Any]:
    task = {
        "completion_rate": score_cards.get("task_success", {})
        .get("metrics", {})
        .get("success", 0.0),
        "position_identity_accuracy": score_cards.get("position_identity", {})
        .get("metrics", {})
        .get("position_identity_accuracy", 0.0),
        "job_f1": score_cards.get("job_constraint", {})
        .get("metrics", {})
        .get("job_f1", 0.0),
        "tool_f1": score_cards.get("tool_call", {})
        .get("metrics", {})
        .get("tool_f1", 0.0),
        "evidence_coverage": score_cards.get("evidence_quality", {})
        .get("metrics", {})
        .get("evidence_coverage", 0.0),
        "claim_groundedness": score_cards.get("claim_groundedness", {})
        .get("metrics", {})
        .get("claim_groundedness", 0.0),
        "answer_completeness": score_cards.get("answer_quality", {})
        .get("metrics", {})
        .get("completeness", 0.0),
    }
    execution = {
        "tool_calls": score_cards.get("efficiency", {})
        .get("metrics", {})
        .get("tool_call_count", len(observation.tool_calls)),
        "agent_turns": score_cards.get("efficiency", {})
        .get("metrics", {})
        .get("agent_steps", observation.agent_steps),
        "latency_ms": score_cards.get("efficiency", {})
        .get("metrics", {})
        .get("latency_ms", observation.latency_ms),
        "input_tokens": score_cards.get("efficiency", {})
        .get("metrics", {})
        .get("input_tokens", observation.input_tokens),
        "output_tokens": score_cards.get("efficiency", {})
        .get("metrics", {})
        .get("output_tokens", observation.output_tokens),
        "estimated_cost": score_cards.get("efficiency", {})
        .get("metrics", {})
        .get("estimated_cost", observation.estimated_cost),
    }
    business = {
        "position_code_match": score_cards.get("position_identity", {})
        .get("metrics", {})
        .get("position_code_match", 0.0),
        "constraint_violation_rate": score_cards.get("job_constraint", {})
        .get("metrics", {})
        .get("constraint_violation_rate", 0.0),
        "citation_support_rate": score_cards.get("rag", {})
        .get("metrics", {})
        .get("citation_support_rate", 0.0),
        "source_authority_score": score_cards.get("evidence_quality", {})
        .get("metrics", {})
        .get("source_authority_score", 0.0),
    }
    answer = {
        "completeness": score_cards.get("answer_quality", {})
        .get("metrics", {})
        .get("completeness", 0.0),
        "clarity": score_cards.get("answer_quality", {})
        .get("metrics", {})
        .get("clarity", 0.0),
        "groundedness": score_cards.get("answer_quality", {})
        .get("metrics", {})
        .get("groundedness_hint", 0.0),
    }
    return {
        "task": task,
        "business": business,
        "answer": answer,
        "execution": execution,
    }


def _classify_failure(reason: str) -> str:
    text = reason.lower()
    if "trace" in text:
        return "TRACE"
    if "tool" in text:
        return "TOOL"
    if "position" in text or "job" in text:
        return "BUSINESS"
    if "evidence" in text or "citation" in text or "grounded" in text:
        return "EVIDENCE"
    if "memory" in text:
        return "MEMORY"
    if "answer" in text or "clarity" in text:
        return "ANSWER"
    return "OTHER"
