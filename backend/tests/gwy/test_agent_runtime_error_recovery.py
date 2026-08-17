from __future__ import annotations

from typing import Any

from app.gwy.agent_runtime.loop import AgentRuntime
from app.gwy.agent_runtime.tools import ToolRegistry


class RecoveryError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class FakeRecoveryClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat_completion_message(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"messages": [dict(message) for message in messages], **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeRecoveryChatService:
    def __init__(self, responses: list[Any]) -> None:
        self.client = FakeRecoveryClient(responses)
        self.summary_calls = 0

    def summarize_compact_context(
        self,
        messages: list[dict[str, Any]],
        *,
        focus: str = "",
    ) -> str:
        self.summary_calls += 1
        return f"summary for {focus or 'recovery'}"


def _runtime(
    chat_service: FakeRecoveryChatService,
    *,
    events: list[dict[str, Any]],
    **kwargs: Any,
) -> AgentRuntime:
    return AgentRuntime(
        chat_service=chat_service,
        tools=ToolRegistry(),
        system_prompt="system",
        on_event=events.append,
        sleep_fn=lambda _: None,
        **kwargs,
    )


def test_transient_llm_error_retries_and_emits_recovery_trace() -> None:
    chat_service = FakeRecoveryChatService(
        [RecoveryError("rate limited", 429), {"role": "assistant", "content": "ok"}]
    )
    events: list[dict[str, Any]] = []

    result = _runtime(chat_service, events=events).run(user_prompt="hello")

    assert result.answer == "ok"
    assert len(chat_service.client.calls) == 2
    recovery_events = [event for event in result.trace if event["event"] == "ErrorRecovery"]
    assert recovery_events
    assert recovery_events[0]["step"] == "transient_retry"
    assert recovery_events[0]["output"]["reason"] == "rate_limit"
    assert any(event["event"] == "ErrorRecovery" for event in events)


def test_max_tokens_escalates_then_retries_without_appending_truncated_output() -> None:
    chat_service = FakeRecoveryChatService(
        [
            {"role": "assistant", "content": "partial", "finish_reason": "length"},
            {"role": "assistant", "content": "complete", "finish_reason": "stop"},
        ]
    )
    events: list[dict[str, Any]] = []

    result = _runtime(chat_service, events=events).run(user_prompt="hello")

    assert result.answer == "complete"
    assert [call["max_tokens"] for call in chat_service.client.calls] == [8000, 64000]
    assert all(len(call["messages"]) == 2 for call in chat_service.client.calls)
    assert any(
        event["event"] == "ErrorRecovery" and event["step"] == "max_tokens_escalate"
        for event in result.trace
    )


def test_prompt_too_long_reactively_compacts_once_then_retries() -> None:
    chat_service = FakeRecoveryChatService(
        [
            RecoveryError("prompt too long", 400),
            {"role": "assistant", "content": "after compact"},
        ]
    )
    events: list[dict[str, Any]] = []

    result = _runtime(
        chat_service,
        events=events,
        compact_token_threshold=999999,
    ).run(user_prompt="hello")

    assert result.answer == "after compact"
    assert chat_service.summary_calls == 1
    assert len(chat_service.client.calls[1]["messages"]) == 1
    assert any(
        event["event"] == "ErrorRecovery" and event["step"] == "reactive_compact"
        for event in result.trace
    )


def test_three_overload_errors_switch_to_fallback_model() -> None:
    chat_service = FakeRecoveryChatService(
        [
            RecoveryError("overloaded", 529),
            RecoveryError("overloaded", 529),
            RecoveryError("overloaded", 529),
            {"role": "assistant", "content": "fallback answer"},
        ]
    )
    events: list[dict[str, Any]] = []

    result = _runtime(
        chat_service,
        events=events,
        fallback_model="backup-model",
    ).run(user_prompt="hello")

    assert result.answer == "fallback answer"
    assert [call["model"] for call in chat_service.client.calls] == [
        None,
        None,
        None,
        "backup-model",
    ]
    assert any(
        event["event"] == "ErrorRecovery" and event["step"] == "fallback_model"
        for event in result.trace
    )
