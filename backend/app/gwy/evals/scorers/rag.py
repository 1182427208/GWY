from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gwy.evals.normalization import normalize_value
from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class RagScore:
    recall_at_k: float
    citation_support_rate: float
    answer_point_coverage: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="rag",
            passed=self.passed,
            metrics={
                "recall_at_k": self.recall_at_k,
                "citation_support_rate": self.citation_support_rate,
                "answer_point_coverage": self.answer_point_coverage,
            },
            failure_reasons=self.failure_reasons,
        )


def score_rag(
    case: EvalCase, observation: AgentObservation, *, top_k: int = 5
) -> RagScore:
    gold_ids = set(case.expected.gold_doc_ids) | set(case.expected.gold_chunk_ids)
    retrieved_ids = _ids_from_records(observation.retrieved_documents[:top_k])
    recall = len(gold_ids & retrieved_ids) / len(gold_ids) if gold_ids else 1.0

    if observation.citations:
        supported = sum(
            1
            for citation in observation.citations
            if _citation_supported(citation, gold_ids)
        )
        support = supported / len(observation.citations)
    else:
        support = 1.0 if not gold_ids else 0.0

    points = case.expected.gold_answer_points
    answer = normalize_value(observation.final_answer)
    coverage = (
        sum(1 for point in points if normalize_value(point) in answer) / len(points)
        if points
        else 1.0
    )
    failures: list[str] = []
    if recall < 1.0:
        failures.append("gold document or chunk not fully retrieved in top-k")
    if support < 1.0:
        failures.append("citations do not fully support expected evidence ids")
    if coverage < 1.0:
        failures.append("answer missed expected answer points")
    return RagScore(recall, support, coverage, not failures, failures)


def _citation_supported(citation: dict[str, Any], gold_ids: set[str]) -> bool:
    ids = _ids_from_records([citation])
    if ids & gold_ids:
        return True
    doc_id = str(citation.get("doc_id") or citation.get("document_id") or "")
    return bool(doc_id and doc_id in gold_ids)


def _ids_from_records(records: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in records:
        for key in (
            "doc_id",
            "document_id",
            "doc_title",
            "source_file",
            "chunk_id",
            "id",
        ):
            value = item.get(key)
            if value not in (None, ""):
                ids.add(str(value))
    return ids
