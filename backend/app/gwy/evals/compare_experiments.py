from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compare_summaries(left_path: str | Path, right_path: str | Path) -> dict[str, Any]:
    left = json.loads(Path(left_path).read_text(encoding="utf-8"))
    right = json.loads(Path(right_path).read_text(encoding="utf-8"))
    left_metrics = dict(left.get("metrics") or {})
    right_metrics = dict(right.get("metrics") or {})
    keys = sorted(set(left_metrics) | set(right_metrics))
    return {
        "left_experiment": left.get("experiment_name"),
        "right_experiment": right.get("experiment_name"),
        "metric_deltas": {
            key: (
                right_metrics.get(key),
                left_metrics.get(key),
                _delta(right_metrics.get(key), left_metrics.get(key)),
            )
            for key in keys
        },
    }


def _delta(right: Any, left: Any) -> float | None:
    if isinstance(right, int | float) and isinstance(left, int | float):
        return float(right) - float(left)
    return None
