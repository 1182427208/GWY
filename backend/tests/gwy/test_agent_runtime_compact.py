from __future__ import annotations

from typing import Any

from app.gwy.agent_runtime.compact import (
    auto_compact,
    estimate_tokens,
    micro_compact,
)
from app.gwy.agent_runtime.loop import AgentRuntime
from app.gwy.agent_runtime.tools import ToolRegistry


class FakeSummarizer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def summarize_compact_context(
        self,
        messages: list[dict[str, Any]],
        *,
        focus: str = "",
    ) -> str:
        self.calls.append({"messages": messages, "focus": focus})
        return "summary: accomplished, current state, decisions"


class FakeTranscriptStore:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save_compact_transcript(
        self,
        messages: list[dict[str, Any]],
        *,
        focus: str = "",
    ) -> dict[str, Any]:
        record = {
            "transcript_id": f"tx-{len(self.saved) + 1}",
            "conversation_id": "conv-1",
            "message_count": len(messages),
            "focus": focus,
        }
        self.saved.append({"messages": messages, "record": record})
        return record

    def save_compact_summary(
        self,
        summary: str,
        *,
        transcript_id: str,
        focus: str = "",
    ) -> None:
        self.saved[-1]["summary"] = {
            "summary": summary,
            "transcript_id": transcript_id,
            "focus": focus,
        }


def test_estimate_tokens_matches_reference_ratio() -> None:
    messages = [{"role": "user", "content": "abcd" * 10}]

    assert estimate_tokens(messages) == len(str(messages)) // 4


def test_micro_compact_replaces_old_large_tool_results_but_keeps_recent_and_read_file() -> None:
    long_output = "x" * 140
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "search"}}]},
        {"role": "tool", "tool_call_id": "1", "content": long_output},
        {"role": "assistant", "tool_calls": [{"id": "2", "function": {"name": "read_file"}}]},
        {"role": "tool", "tool_call_id": "2", "content": long_output},
        {"role": "assistant", "tool_calls": [{"id": "3", "function": {"name": "search"}}]},
        {"role": "tool", "tool_call_id": "3", "content": long_output},
        {"role": "assistant", "tool_calls": [{"id": "4", "function": {"name": "search"}}]},
        {"role": "tool", "tool_call_id": "4", "content": long_output},
        {"role": "assistant", "tool_calls": [{"id": "5", "function": {"name": "search"}}]},
        {"role": "tool", "tool_call_id": "5", "content": long_output},
    ]

    compacted, meta = micro_compact(messages)

    assert compacted[1]["content"] == "[Previous: used search]"
    assert compacted[3]["content"] == long_output
    assert compacted[5]["content"] == long_output
    assert compacted[7]["content"] == long_output
    assert compacted[9]["content"] == long_output
    assert meta is not None
    assert meta["strategy"] == "micro_compact"
    assert meta["compacted_tool_result_count"] == 1


def test_auto_compact_saves_transcript_and_replaces_messages_with_summary() -> None:
    summarizer = FakeSummarizer()
    store = FakeTranscriptStore()
    messages = [{"role": "user", "content": "hello"}]

    compacted, meta = auto_compact(
        messages,
        summarizer=summarizer,
        transcript_store=store,
        focus="preserve preferences",
    )

    assert len(store.saved) == 1
    assert summarizer.calls[0]["focus"] == "preserve preferences"
    assert compacted == [
        {
            "role": "user",
            "content": (
                "[Conversation compressed. Transcript: tx-1]\n\n"
                "summary: accomplished, current state, decisions"
            ),
        }
    ]
    assert store.saved[0]["summary"]["summary"] == "summary: accomplished, current state, decisions"
    assert meta["strategy"] == "auto_compact"


class FakeChatClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat_completion_message(self, messages: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "compact-1",
                        "function": {
                            "name": "compact",
                            "arguments": '{"focus":"keep decision"}',
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "done"}


class FakeChatService:
    def __init__(self) -> None:
        self.client = FakeChatClient()

    def summarize_compact_context(
        self,
        messages: list[dict[str, Any]],
        *,
        focus: str = "",
    ) -> str:
        return f"manual summary: {focus}"


def test_agent_runtime_compact_tool_triggers_manual_summary_compaction() -> None:
    store = FakeTranscriptStore()
    registry = ToolRegistry()
    runtime = AgentRuntime(
        chat_service=FakeChatService(),
        tools=registry,
        system_prompt="system",
        transcript_store=store,
    )

    result = runtime.run(user_prompt="please compact")

    assert result.answer == "done"
    assert len(store.saved) == 1
    assert store.saved[0]["summary"]["summary"] == "manual summary: keep decision"
    assert any(
        event["event"] == "Compact" and event["step"] == "manual_compact"
        for event in result.trace
    )

