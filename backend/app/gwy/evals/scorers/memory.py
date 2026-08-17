from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gwy.evals.normalization import normalize_value
from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class MemoryScore:
    memory_field_accuracy: float
    memory_update_accuracy: float
    leakage_count: int
    stale_field_usage_count: int
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="memory",
            passed=self.passed,
            metrics={
                "memory_field_accuracy": self.memory_field_accuracy,
                "memory_update_accuracy": self.memory_update_accuracy,
                "leakage_count": self.leakage_count,
                "stale_field_usage_count": self.stale_field_usage_count,
            },
            failure_reasons=self.failure_reasons,
        )


def score_memory(case: EvalCase, observation: AgentObservation) -> MemoryScore:
    expected = case.expected.memory_after
    total = len(expected)
    correct = 0
    for key, value in expected.items():
        actual = observation.memory_after.get(key)
        if _contains_expected(actual, value):
            correct += 1
    accuracy = correct / total if total else 1.0
    update_accuracy = _update_accuracy(observation.memory_after, expected)
    failures = []
    if accuracy < 1.0:
        failures.append("memory_after missed expected fields")
    if observation.memory_leakage_count:
        failures.append(f"memory leakage count: {observation.memory_leakage_count}")
    if observation.stale_field_usage_count:
        failures.append(
            f"stale field usage count: {observation.stale_field_usage_count}"
        )
    return MemoryScore(
        memory_field_accuracy=accuracy,
        memory_update_accuracy=update_accuracy,
        leakage_count=observation.memory_leakage_count,
        stale_field_usage_count=observation.stale_field_usage_count,
        passed=not failures,
        failure_reasons=failures,
    )


def _contains_expected(actual: Any, expected: Any) -> bool:
    actual_norm = normalize_value(actual)
    expected_norm = normalize_value(expected)
    if isinstance(expected_norm, list) and isinstance(actual_norm, list):
        return set(expected_norm).issubset(set(actual_norm))
    return actual_norm == expected_norm


def _update_accuracy(after: dict[str, Any], expected: dict[str, Any]) -> float:
    if not expected:
        return 1.0
    correct = 0
    for key, expected_value in expected.items():
        if _contains_expected(after.get(key), expected_value):
            correct += 1
    return correct / len(expected)
