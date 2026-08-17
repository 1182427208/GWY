from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.gwy.evals.schemas import AgentObservation, ToolCall


def normalize_agent_output(output: Any) -> AgentObservation:
    """Convert service dictionaries and AgentRuntimeResult into a stable observation."""
    if isinstance(output, AgentObservation):
        return output
    payload = _as_mapping(output)
    state = _as_mapping(payload.get("state"))
    metadata = _as_mapping(payload.get("metadata_json"))
    trace = _as_records(
        payload.get("retrieval_trace")
        or payload.get("trace")
        or state.get("retrieval_trace")
        or state.get("trace")
    )
    recommendations = _as_records(
        payload.get("recommendations") or state.get("recommendations")
    )
    resolved_position = _as_mapping(
        payload.get("resolved_position")
        or state.get("resolved_position")
        or payload.get("position")
    )
    returned_job_ids = [
        str(item.get("position_id") or item.get("id"))
        for item in recommendations
        if item.get("position_id") or item.get("id")
    ]
    usage = _as_mapping(payload.get("usage") or metadata.get("usage"))
    memory_after = _as_mapping(
        payload.get("memory_after")
        or state.get("memory_after")
        or metadata.get("memory_after")
    )
    raw_answer = payload.get("answer") or payload.get("report") or state.get("report")
    return AgentObservation(
        final_answer=str(raw_answer or ""),
        status=str(payload.get("status") or "success"),
        task_contract=_as_mapping(
            payload.get("task_contract") or state.get("task_contract")
        ),
        validation=_as_mapping(payload.get("validation") or state.get("validation")),
        resolved_position=resolved_position,
        returned_job_ids=returned_job_ids,
        returned_jobs=recommendations,
        citations=_as_records(payload.get("citations") or state.get("citations")),
        retrieved_documents=_as_records(
            payload.get("rerank_results") or state.get("rerank_results")
        ),
        claims=_as_records(payload.get("claims") or state.get("claims")),
        tool_calls=_extract_tool_calls(trace),
        memory_before=_as_mapping(
            payload.get("memory_before") or state.get("memory_before")
        ),
        memory_after=memory_after,
        memory_leakage_count=int(payload.get("memory_leakage_count") or 0),
        stale_field_usage_count=int(payload.get("stale_field_usage_count") or 0),
        agent_steps=int(payload.get("agent_steps") or _count_agent_steps(trace)),
        latency_ms=int(payload.get("latency_ms") or _latency_from_trace(trace)),
        input_tokens=_optional_int(
            payload.get("input_tokens") or usage.get("input_tokens")
        ),
        output_tokens=_optional_int(
            payload.get("output_tokens") or usage.get("output_tokens")
        ),
        estimated_cost=_optional_float(
            payload.get("estimated_cost") or usage.get("estimated_cost")
        ),
        raw_output=payload,
        trace=trace,
    )


def _extract_tool_calls(trace: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for event in trace:
        event_name = str(event.get("event") or event.get("type") or "")
        tool_name = str(
            event.get("tool") or event.get("tool_name") or event.get("name") or ""
        )
        if event_name not in {"ToolUse", "PostToolUse"} or not tool_name:
            continue
        if event_name == "ToolUse":
            calls.append(
                ToolCall(
                    tool=tool_name,
                    arguments=_as_mapping(event.get("input") or event.get("arguments")),
                    success=True,
                    latency_ms=_optional_int(event.get("elapsed_ms")),
                )
            )
        elif calls and calls[-1].tool == tool_name:
            calls[-1].success = str(event.get("status") or "done") not in {
                "error",
                "failed",
                "denied",
            }
            calls[-1].latency_ms = _optional_int(event.get("elapsed_ms"))
            calls[-1].error = str(event.get("detail") or "") or None
    return calls


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, dict) else {}
    if hasattr(value, "__dict__"):
        attributes = dict(vars(value))
        if attributes:
            return attributes
    fields = (
        "answer",
        "trace",
        "state",
        "recommendations",
        "citations",
        "report",
        "status",
    )
    return {name: getattr(value, name) for name in fields if hasattr(value, name)}


def _as_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list | tuple):
        return []
    records: list[dict[str, Any]] = []
    for item in value:
        record = _as_mapping(item)
        if record:
            records.append(record)
    return records


def _count_agent_steps(trace: list[dict[str, Any]]) -> int:
    return sum(1 for event in trace if event.get("event") in {"LLMStart", "ToolUse"})


def _latency_from_trace(trace: list[dict[str, Any]]) -> int:
    return sum(int(event.get("elapsed_ms") or 0) for event in trace)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
