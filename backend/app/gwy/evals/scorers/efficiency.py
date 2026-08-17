from __future__ import annotations

from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


def score_efficiency(case: EvalCase, observation: AgentObservation) -> ScoreBundle:
    _ = case
    return ScoreBundle(
        name="efficiency",
        passed=True,
        metrics={
            "tool_call_count": len(observation.tool_calls),
            "agent_steps": observation.agent_steps,
            "latency_ms": observation.latency_ms,
            "input_tokens": observation.input_tokens,
            "output_tokens": observation.output_tokens,
            "estimated_cost": observation.estimated_cost,
        },
    )
