from __future__ import annotations

from dataclasses import dataclass, field

from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class AnswerQualityScore:
    completeness: float
    clarity: float
    groundedness_hint: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, float]:
        return {
            "completeness": self.completeness,
            "clarity": self.clarity,
            "groundedness_hint": self.groundedness_hint,
        }

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="answer_quality",
            passed=self.passed,
            metrics=self.metrics,
            failure_reasons=self.failure_reasons,
        )


def score_answer_quality(
    case: EvalCase, observation: AgentObservation
) -> AnswerQualityScore:
    required_report = case.expected.report_required
    answer = str(observation.final_answer or "").strip()
    completeness = 1.0 if answer else 0.0
    if required_report and not answer:
        completeness = 0.0
    clarity = 1.0 if answer and len(answer) >= 4 else 0.0
    groundedness_hint = 1.0 if observation.citations or observation.retrieved_documents else 0.0
    failures: list[str] = []
    if not answer:
        failures.append("final answer is empty")
    if required_report and not answer:
        failures.append("report required but final answer missing")
    return AnswerQualityScore(
        completeness=completeness,
        clarity=clarity,
        groundedness_hint=groundedness_hint,
        passed=not failures,
        failure_reasons=failures,
    )
