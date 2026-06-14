from __future__ import annotations

from types import SimpleNamespace

from app.gwy.llm.siliconflow_client import SiliconFlowClient


class FakeStreamResponse:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def __iter__(self):
        yield from self._chunks


class RecordingChatCompletions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return self.response


class RecordingOpenAIClient:
    def __init__(self, response: object) -> None:
        self.chat = SimpleNamespace(
            completions=RecordingChatCompletions(response),
        )


def test_siliconflow_stream_parser_emits_reasoning_and_content() -> None:
    response = FakeStreamResponse(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(reasoning_content="think step 1")
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(delta=SimpleNamespace(content="final answer"))
                ]
            ),
        ]
    )

    client = SiliconFlowClient(client=RecordingOpenAIClient(response))

    events = list(client.chat_completions_stream([{"role": "user", "content": "hi"}]))

    assert events == [
        {"type": "reasoning", "text": "think step 1"},
        {"type": "content", "text": "final answer"},
    ]


def test_siliconflow_stream_enables_thinking_by_default() -> None:
    response = FakeStreamResponse([])
    client = SiliconFlowClient(
        client=RecordingOpenAIClient(response),
        chat_model="Qwen/Qwen3-VL-32B-Thinking",
    )

    list(client.chat_completions_stream([{"role": "user", "content": "hello"}]))

    request = client._chat_client().chat.completions.requests[0]  # noqa: SLF001
    assert "enable_thinking" not in request["extra_body"]
    assert request["extra_body"]["thinking_budget"] == 1024


def test_siliconflow_stream_enables_thinking_for_supported_models() -> None:
    response = FakeStreamResponse([])
    client = SiliconFlowClient(
        client=RecordingOpenAIClient(response),
        chat_model="Qwen/Qwen3-32B",
    )

    list(client.chat_completions_stream([{"role": "user", "content": "hello"}]))

    request = client._chat_client().chat.completions.requests[0]  # noqa: SLF001
    assert request["extra_body"]["enable_thinking"] is True
    assert request["extra_body"]["thinking_budget"] == 1024


def test_siliconflow_chat_completion_uses_openai_style_response() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello world"),
            )
        ]
    )
    client = SiliconFlowClient(client=RecordingOpenAIClient(response))

    content = client.chat_completions([{"role": "user", "content": "hello"}])

    assert content == "hello world"
