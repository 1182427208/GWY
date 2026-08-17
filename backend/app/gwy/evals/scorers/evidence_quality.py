from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gwy.evals.normalization import normalize_value
from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class EvidenceQualityScore:
    evidence_coverage: float
    source_authority_score: float
    evidence_position_match_rate: float
    evidence_year_match_rate: float
    evidence_conflict_rate: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, float]:
        return {
            "evidence_coverage": self.evidence_coverage,
            "source_authority_score": self.source_authority_score,
            "evidence_position_match_rate": self.evidence_position_match_rate,
            "evidence_year_match_rate": self.evidence_year_match_rate,
            "evidence_conflict_rate": self.evidence_conflict_rate,
        }

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="evidence_quality",
            passed=self.passed,
            metrics=self.metrics,
            failure_reasons=self.failure_reasons,
        )


def score_evidence_quality(
    case: EvalCase, observation: AgentObservation
) -> EvidenceQualityScore:
    citation_items = [dict(item or {}) for item in observation.citations or []]
    evidence_items = citation_items + [dict(item or {}) for item in observation.retrieved_documents or []]
    total = len(evidence_items)
    if total == 0:
        return EvidenceQualityScore(0.0, 0.0, 0.0, 0.0, 1.0, False, ["no evidence observed"])

    expected = dict(case.expected.expected_position or {})
    expected_code = str(expected.get("position_code") or "").strip()
    expected_year = expected.get("year")

    supported = 0
    authority_score = 0.0
    position_matches = 0
    position_considered = 0
    year_matches = 0
    year_considered = 0
    conflicts = 0

    for item in evidence_items:
        source_type = str(item.get("source_type") or item.get("doc_type") or "").lower()
        item_code = str(item.get("position_code") or item.get("position_id") or "")
        item_year = item.get("year")
        if item_code or item.get("doc_id") or item.get("chunk_id"):
            supported += 1
        if item_code:
            position_considered += 1
            if not expected_code or normalize_value(expected_code) == normalize_value(item_code):
                position_matches += 1
        if expected_year is not None:
            if source_type in {"official", "gov", "government", "authority", "policy", "document", "pdf", "milvus", "doc"}:
                year_considered += 1
                if item_year is None or normalize_value(expected_year) == normalize_value(item_year):
                    year_matches += 1
                else:
                    conflicts += 1
            else:
                year_considered += 1
                year_matches += 1
        elif expected_year is None:
            year_considered += 1
            year_matches += 1

    if citation_items:
        for item in citation_items:
            source_type = str(
                item.get("source_type") or item.get("doc_type") or ""
            ).lower()
            authority_score += _authority_weight(source_type, item)
        source_authority = authority_score / len(citation_items)
    else:
        source_authority = 0.0

    coverage = supported / total if total else 0.0
    position_match_rate = (
        position_matches / position_considered if position_considered else 1.0
    )
    year_match_rate = year_matches / year_considered if year_considered else 1.0
    conflict_rate = conflicts / total if total else 0.0

    failures: list[str] = []
    if coverage < 1.0:
        failures.append("evidence coverage is incomplete")
    if source_authority <= 0.0:
        failures.append("evidence authority is too weak")
    if expected_code and position_match_rate < 1.0:
        failures.append("evidence position mismatch")
    if expected_year is not None and year_match_rate < 1.0:
        failures.append("evidence year mismatch")
    return EvidenceQualityScore(
        evidence_coverage=coverage,
        source_authority_score=source_authority,
        evidence_position_match_rate=position_match_rate,
        evidence_year_match_rate=year_match_rate,
        evidence_conflict_rate=conflict_rate,
        passed=not failures,
        failure_reasons=failures,
    )


def _authority_weight(source_type: str, item: dict[str, Any]) -> float:
    if source_type in {"official", "gov", "government", "authority", "policy"}:
        return 1.0
    if source_type in {"document", "pdf", "milvus", "doc"}:
        return 0.8
    if source_type in {"web", "news", "article", "forum"}:
        return 0.0
    if item.get("source_url"):
        return 0.3
    return 0.0
