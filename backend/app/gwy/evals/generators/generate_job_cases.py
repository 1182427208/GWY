from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def build_job_case(
    *,
    case_id: str,
    query: str,
    profile: dict[str, Any],
    matching_job_ids: Iterable[str],
    forbidden_job_ids: Iterable[str] = (),
    notes: str = "",
) -> dict[str, Any]:
    """Build a case from human/database-confirmed IDs; no IDs are synthesized."""
    return {
        "case_id": case_id,
        "task_type": "job_filter",
        "split": "dev",
        "query": query,
        "profile": profile,
        "expected": {
            "job_ids": [str(item) for item in matching_job_ids],
            "forbidden_job_ids": [str(item) for item in forbidden_job_ids],
        },
        "metadata": {"notes": notes, "ground_truth_status": "needs_review"},
    }


def write_cases(cases: Iterable[dict[str, Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
