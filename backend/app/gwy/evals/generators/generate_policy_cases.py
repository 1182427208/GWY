from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def build_policy_case(
    *,
    case_id: str,
    query: str,
    gold_doc_ids: Iterable[str],
    gold_chunk_ids: Iterable[str] = (),
    answer_points: Iterable[str] = (),
    notes: str = "",
) -> dict[str, Any]:
    """Build a policy case from reviewed source/chunk metadata."""
    return {
        "case_id": case_id,
        "task_type": "policy_qa",
        "split": "dev",
        "query": query,
        "expected": {
            "gold_doc_ids": [str(item) for item in gold_doc_ids],
            "gold_chunk_ids": [str(item) for item in gold_chunk_ids],
            "gold_answer_points": list(answer_points),
        },
        "metadata": {"notes": notes, "ground_truth_status": "needs_review"},
    }
