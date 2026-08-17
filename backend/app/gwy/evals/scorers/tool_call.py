from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gwy.evals.normalization import values_equal
from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class ToolCallScore:
    required_tool_recall: float
    tool_precision: float
    tool_f1: float
    forbidden_tool_violation_rate: float
    argument_accuracy: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="tool_call",
            passed=self.passed,
            metrics={
                "required_tool_recall": self.required_tool_recall,
                "tool_precision": self.tool_precision,
                "tool_f1": self.tool_f1,
                "forbidden_tool_violation_rate": self.forbidden_tool_violation_rate,
                "argument_accuracy": self.argument_accuracy,
            },
            failure_reasons=self.failure_reasons,
        )


def score_tool_calls(case: EvalCase, observation: AgentObservation) -> ToolCallScore:
    expected = case.expected
    called = [call.tool for call in observation.tool_calls]
    called_set = set(called)
    required = set(expected.required_tools)
    forbidden = set(expected.forbidden_tools)
    allowed = required | set(expected.optional_tools)

    required_hits = len(required & called_set)
    required_recall = required_hits / len(required) if required else 1.0
    relevant_calls = [name for name in called if not allowed or name in allowed]
    precision = (
        len(relevant_calls) / len(called) if called else (1.0 if not required else 0.0)
    )
    f1 = (
        2 * precision * required_recall / (precision + required_recall)
        if precision + required_recall
        else 0.0
    )
    forbidden_hits = len(forbidden & called_set)
    forbidden_rate = forbidden_hits / len(forbidden) if forbidden else 0.0
    arg_accuracy = _argument_accuracy(expected.tool_arguments, observation)
    forbidden_argument_hits = _forbidden_argument_hits(
        expected.forbidden_arguments, observation
    )

    failures: list[str] = []
    missing = sorted(required - called_set)
    if missing:
        failures.append("missing required tools: " + ", ".join(missing))
    forbidden_called = sorted(forbidden & called_set)
    if forbidden_called:
        failures.append("forbidden tools called: " + ", ".join(forbidden_called))
    if (
        expected.maximum_tool_calls is not None
        and len(called) > expected.maximum_tool_calls
    ):
        failures.append(
            f"tool call count {len(called)} exceeded maximum {expected.maximum_tool_calls}"
        )
    if arg_accuracy < 1.0:
        failures.append("tool arguments did not match expected fields")
    if forbidden_argument_hits:
        failures.append("forbidden tool arguments were observed")

    return ToolCallScore(
        required_tool_recall=required_recall,
        tool_precision=precision,
        tool_f1=f1,
        forbidden_tool_violation_rate=forbidden_rate,
        argument_accuracy=arg_accuracy,
        passed=not failures,
        failure_reasons=failures,
    )


def _argument_accuracy(
    expected_arguments: dict[str, dict[str, Any]],
    observation: AgentObservation,
) -> float:
    total = 0
    correct = 0
    by_tool = {call.tool: call.arguments for call in observation.tool_calls}
    for tool_name, fields in expected_arguments.items():
        actual = by_tool.get(tool_name, {})
        for key, expected in _flatten(fields).items():
            total += 1
            if key in _flatten(actual) and values_equal(
                expected, _flatten(actual)[key]
            ):
                correct += 1
    return correct / total if total else 1.0


def _forbidden_argument_hits(
    forbidden_arguments: dict[str, dict[str, Any]], observation: AgentObservation
) -> int:
    hits = 0
    for call in observation.tool_calls:
        fields = forbidden_arguments.get(call.tool)
        if not fields:
            continue
        actual = _flatten(call.arguments)
        expected = _flatten(fields)
        hits += sum(
            1
            for key, value in expected.items()
            if key in actual and values_equal(value, actual[key])
        )
    return hits


def _flatten(payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten(value, path))
        else:
            flattened[path] = value
    return flattened
