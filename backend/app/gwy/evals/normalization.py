from __future__ import annotations

import re
from typing import Any

_SYNONYMS = {
    "master": "硕士",
    "硕士研究生": "硕士",
    "研究生": "硕士",
    "bachelor": "本科",
    "学士": "本科",
    "本科生": "本科",
    "不限": "不限",
}


def normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): normalize_value(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple | set):
        normalized = [normalize_value(item) for item in value]
        return sorted(normalized, key=repr)
    if isinstance(value, str):
        text = re.sub(r"\s+", "", value.strip().lower())
        if text.isdigit():
            return int(text)
        return _SYNONYMS.get(text, text)
    return value


def values_equal(expected: Any, actual: Any) -> bool:
    return normalize_value(expected) == normalize_value(actual)
