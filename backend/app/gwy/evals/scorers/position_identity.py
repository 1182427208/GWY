from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gwy.evals.normalization import normalize_value
from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class PositionIdentityScore:
    position_name_match: float
    department_match: float
    position_code_match: float
    year_match: float
    position_identity_accuracy: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, float]:
        return {
            "position_name_match": self.position_name_match,
            "department_match": self.department_match,
            "position_code_match": self.position_code_match,
            "year_match": self.year_match,
            "position_identity_accuracy": self.position_identity_accuracy,
        }

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="position_identity",
            passed=self.passed,
            metrics=self.metrics,
            failure_reasons=self.failure_reasons,
        )


def score_position_identity(
    case: EvalCase, observation: AgentObservation
) -> PositionIdentityScore:
    expected = dict(case.expected.expected_position or {})
    actual = _resolved_position(observation)
    if not expected:
        return PositionIdentityScore(1.0, 1.0, 1.0, 1.0, 1.0, True)

    field_scores = {
        "department": _match(expected.get("department"), actual.get("department")),
        "position_name": _match(
            expected.get("position_name"), actual.get("position_name")
        ),
        "position_code": _match(
            expected.get("position_code"), actual.get("position_code")
        ),
        "year": _match(expected.get("year"), actual.get("year")),
    }
    values = list(field_scores.values())
    accuracy = sum(values) / len(values) if values else 1.0
    failures = [
        f"{field} mismatch"
        for field, matched in field_scores.items()
        if not matched and expected.get(field) not in (None, "", [])
    ]
    return PositionIdentityScore(
        position_name_match=field_scores["position_name"],
        department_match=field_scores["department"],
        position_code_match=field_scores["position_code"],
        year_match=field_scores["year"],
        position_identity_accuracy=accuracy,
        passed=not failures,
        failure_reasons=failures,
    )


def _resolved_position(observation: AgentObservation) -> dict[str, Any]:
    if observation.resolved_position:
        return dict(observation.resolved_position)
    raw_position = observation.raw_output.get("resolved_position") or observation.raw_output.get("position")
    if isinstance(raw_position, dict):
        return dict(raw_position)
    if observation.returned_jobs:
        job = dict(observation.returned_jobs[0] or {})
        return {
            "department": job.get("department") or job.get("department_name"),
            "position_name": job.get("position_name")
            or job.get("job_title")
            or job.get("title"),
            "position_code": job.get("position_code") or job.get("code"),
            "year": job.get("year") or job.get("exam_year"),
        }
    return {}


def _match(expected: Any, actual: Any) -> float:
    if expected in (None, "", []):
        return 1.0
    return 1.0 if normalize_value(expected) == normalize_value(actual) else 0.0
