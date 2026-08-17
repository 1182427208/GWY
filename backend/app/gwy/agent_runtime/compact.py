from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Protocol

COMPACT_TOKEN_THRESHOLD = 50000
COMPACT_KEEP_RECENT_TOOL_RESULTS = 3
COMPACT_PRESERVE_RESULT_TOOLS = {"read_file"}
COMPACT_TOOL_RESULT_MIN_CHARS = 100
COMPACT_CONVERSATION_TEXT_CHARS = 80000


class CompactSummarizer(Protocol):
    def summarize_compact_context(
        self,
        messages: list[dict[str, Any]],
        *,
        focus: str = "",
    ) -> str: ...


class CompactTranscriptStore(Protocol):
    def save_compact_transcript(
        self,
        messages: list[dict[str, Any]],
        *,
        focus: str = "",
    ) -> dict[str, Any]: ...

    def save_compact_summary(
        self,
        summary: str,
        *,
        transcript_id: str,
        focus: str = "",
    ) -> None: ...


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Reference-compatible rough token count: about four chars per token."""
    return len(str(messages)) // 4


def estimate_context_size(messages: list[dict[str, Any]]) -> int:
    return len(json.dumps(messages, ensure_ascii=False, default=str))


def micro_compact(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = COMPACT_KEEP_RECENT_TOOL_RESULTS,
    preserve_result_tools: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Replace old large tool results with learn-claude-code placeholders."""
    preserve = preserve_result_tools or COMPACT_PRESERVE_RESULT_TOOLS
    compacted = deepcopy(messages)
    tool_name_by_call_id = _tool_name_by_call_id(compacted)
    tool_results = [
        (idx, message)
        for idx, message in enumerate(compacted)
        if message.get("role") == "tool"
    ]
    if len(tool_results) <= keep_recent:
        return compacted, None

    compacted_count = 0
    preserved_count = 0
    for _, message in tool_results[:-keep_recent]:
        content = message.get("content")
        if not isinstance(content, str) or len(content) <= COMPACT_TOOL_RESULT_MIN_CHARS:
            preserved_count += 1
            continue
        tool_call_id = str(message.get("tool_call_id") or "")
        tool_name = tool_name_by_call_id.get(tool_call_id, "unknown")
        if tool_name in preserve:
            preserved_count += 1
            continue
        message["content"] = f"[Previous: used {tool_name}]"
        compacted_count += 1

    if compacted_count == 0:
        return compacted, None
    return compacted, {
        "strategy": "micro_compact",
        "tool_result_count": len(tool_results),
        "compacted_tool_result_count": compacted_count,
        "preserved_tool_result_count": preserved_count + keep_recent,
        "message_count": len(compacted),
    }


def auto_compact(
    messages: list[dict[str, Any]],
    *,
    summarizer: CompactSummarizer,
    transcript_store: CompactTranscriptStore | None = None,
    focus: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Save transcript, summarize continuity, and replace messages with summary."""
    transcript_record: dict[str, Any] = {}
    if transcript_store is not None:
        transcript_record = transcript_store.save_compact_transcript(
            messages,
            focus=focus,
        )
    transcript_id = str(
        transcript_record.get("transcript_id")
        or transcript_record.get("id")
        or "memory"
    )
    summary = summarizer.summarize_compact_context(messages, focus=focus).strip()
    if not summary:
        summary = "No summary generated."
    if transcript_store is not None:
        transcript_store.save_compact_summary(
            summary,
            transcript_id=transcript_id,
            focus=focus,
        )
    compacted = [
        {
            "role": "user",
            "content": f"[Conversation compressed. Transcript: {transcript_id}]\n\n{summary}",
        }
    ]
    return compacted, {
        "strategy": "auto_compact",
        "transcript_id": transcript_id,
        "focus": focus,
        "message_count_before": len(messages),
        "message_count_after": len(compacted),
        "tokens_before": estimate_tokens(messages),
        "tokens_after": estimate_tokens(compacted),
        "size_before": estimate_context_size(messages),
        "size_after": estimate_context_size(compacted),
    }


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    max_messages: int = 40,
    max_chars: int = 80000,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Backward-compatible wrapper for older callers."""
    size_before = estimate_context_size(messages)
    if len(messages) <= max_messages and size_before <= max_chars:
        return messages, None

    head = messages[:3]
    tail = messages[-(max_messages - len(head)) :]
    compacted = [
        *head,
        {
            "role": "system",
            "content": (
                f"[context compacted: removed {max(0, len(messages) - len(head) - len(tail))} "
                "middle messages; re-run tools if exact old output is needed]"
            ),
        },
        *tail,
    ]
    return compacted, {
        "strategy": "snip_compact",
        "message_count_before": len(messages),
        "message_count_after": len(compacted),
        "size_before": size_before,
        "size_after": estimate_context_size(compacted),
    }


def _tool_name_by_call_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in list(message.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "")
            function = call.get("function") or {}
            name = str(function.get("name") or "unknown")
            if call_id:
                names[call_id] = name
    return names
