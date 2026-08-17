from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gwy.evals.normalization import normalize_value
from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class ClaimGroundednessScore:
    claim_count: int
    supported_claim_count: int
    claim_groundedness: float
    unsupported_claim_rate: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, float]:
        return {
            "claim_count": float(self.claim_count),
            "supported_claim_count": float(self.supported_claim_count),
            "claim_groundedness": self.claim_groundedness,
            "unsupported_claim_rate": self.unsupported_claim_rate,
        }

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="claim_groundedness",
            passed=self.passed,
            metrics=self.metrics,
            failure_reasons=self.failure_reasons,
        )


def score_claim_groundedness(
    case: EvalCase, observation: AgentObservation
) -> ClaimGroundednessScore:
    _ = case
    claims = list(observation.claims or [])
    if not claims:
        raw_claims = observation.raw_output.get("claims")
        if isinstance(raw_claims, list):
            claims = [dict(item or {}) for item in raw_claims if isinstance(item, dict)]

    if not claims:
        has_answer = bool(str(observation.final_answer).strip())
        return ClaimGroundednessScore(0, 0, 1.0 if has_answer else 0.0, 0.0 if has_answer else 1.0, has_answer, [] if has_answer else ["no claims observed"])

    supported = 0
    for claim in claims:
        if _claim_supported(claim, observation):
            supported += 1

    claim_count = len(claims)
    groundedness = supported / claim_count if claim_count else 1.0
    unsupported_rate = 1 - groundedness if claim_count else 0.0
    failures = []
    if unsupported_rate > 0:
        failures.append("unsupported claims observed")
    return ClaimGroundednessScore(
        claim_count=claim_count,
        supported_claim_count=supported,
        claim_groundedness=groundedness,
        unsupported_claim_rate=unsupported_rate,
        passed=not failures,
        failure_reasons=failures,
    )


def _claim_supported(claim: dict[str, Any], observation: AgentObservation) -> bool:
    if claim.get("supported") is True:
        return True
    if claim.get("supported") is False:
        return False
    evidence_ids = {str(item) for item in claim.get("evidence_ids") or [] if item}
    if evidence_ids:
        available = {
            str(item.get("doc_id") or item.get("document_id") or item.get("chunk_id"))
            for item in observation.citations
            if isinstance(item, dict)
        }
        return bool(evidence_ids & available)
    text = str(claim.get("text") or "").strip()
    return bool(text and normalize_value(text) in normalize_value(observation.final_answer))
