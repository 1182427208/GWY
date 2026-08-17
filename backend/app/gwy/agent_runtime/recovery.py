from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

INITIAL_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 64000
MAX_TRANSIENT_RETRIES = 10
MAX_CONTINUATIONS = 3
MAX_OVERLOADS_BEFORE_FALLBACK = 3
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 32.0


@dataclass(slots=True)
class RecoveryState:
    current_model: str | None = None
    max_tokens: int = INITIAL_MAX_TOKENS
    transient_retries: int = 0
    continuations: int = 0
    consecutive_overloads: int = 0
    has_escalated_tokens: bool = False
    attempted_reactive_compact: bool = False


def classify_llm_error(error: BaseException) -> str:
    status_code = _status_code(error)
    message = _error_text(error)
    if _is_prompt_too_long(message):
        return "prompt_too_long"
    if status_code == 429 or "rate limit" in message or "rate_limit" in message:
        return "rate_limit"
    if status_code == 529 or "overloaded" in message or "overload" in message:
        return "overloaded"
    if status_code in {408, 500, 502, 503, 504} or _is_network_error(error):
        return "transient"
    return "non_retryable"


def retry_after_seconds(error: BaseException) -> float | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            value = headers.get("retry-after") or headers.get("Retry-After")
            if value is not None:
                try:
                    return max(0.0, float(value))
                except (TypeError, ValueError):
                    pass
        current = current.__cause__ or current.__context__
    return None


def retry_delay(attempt: int, *, retry_after: float | None = None) -> float:
    if retry_after is not None:
        return retry_after
    base = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
    return base + random.uniform(0.0, base * 0.25)


def is_truncated_response(response: dict[str, Any]) -> bool:
    reason = str(response.get("finish_reason") or response.get("stop_reason") or "")
    return reason in {"length", "max_tokens", "max_output_tokens"}


def _status_code(error: BaseException) -> int | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status_code = getattr(current, "status_code", None)
        if status_code is None:
            response = getattr(current, "response", None)
            status_code = getattr(response, "status_code", None)
        try:
            if status_code is not None:
                return int(status_code)
        except (TypeError, ValueError):
            pass
        current = current.__cause__ or current.__context__
    return None


def _error_text(error: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current).lower())
        current = current.__cause__ or current.__context__
    return " ".join(parts)


def _is_prompt_too_long(message: str) -> bool:
    markers = (
        "prompt too long",
        "context length",
        "maximum context",
        "context window",
        "token limit",
        "too many tokens",
    )
    return any(marker in message for marker in markers)


def _is_network_error(error: BaseException) -> bool:
    names = {type(error).__name__.lower()}
    current = error.__cause__ or error.__context__
    while current is not None:
        names.add(type(current).__name__.lower())
        current = current.__cause__ or current.__context__
    return any(
        marker in name
        for name in names
        for marker in ("timeout", "connect", "connection", "network")
    )
