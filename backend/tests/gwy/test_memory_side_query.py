from __future__ import annotations

from typing import Any

from app.gwy.agent_runtime.builtin_tools import register_builtin_tools
from app.gwy.agent_runtime.loop import AgentRuntime
from app.gwy.agent_runtime.tools import ToolContext, ToolRegistry
from app.gwy.services.memory_side_query_service import MemorySideQueryService
from app.gwy.services.policy_rag_service import PolicyRagService


class FakeSelectorChatService:
    def __init__(self, response: str = "") -> None:
        self.response = response
        self.calls: list[list[dict[str, Any]]] = []

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.calls.append(messages)
        return self.response


def _cards() -> list[dict[str, Any]]:
    return [
        {
            "name": "user-profile",
            "description": "user education and target region",
            "type": "user",
            "scope": "user",
            "content": "major=law; region=Zhejiang",
        },
        {
            "name": "old-project-context",
            "description": "old project migration context",
            "type": "project",
            "scope": "project",
            "content": "legacy API",
        },
    ]


def test_side_query_selects_only_valid_memory_cards() -> None:
    chat = FakeSelectorChatService(
        '{"selected_memories":["user-profile","missing-memory","user-profile"]}'
    )
    service = MemorySideQueryService(chat_service=chat)

    result = service.retrieve(query="select Zhejiang law positions", cards=_cards())

    assert result["status"] == "selected"
    assert result["selected_names"] == ["user-profile"]
    assert "major=law" in result["memory_text"]
    assert len(chat.calls) == 1


def test_side_query_failure_does_not_fallback_to_direct_memory_loading() -> None:
    chat = FakeSelectorChatService("not-json")
    service = MemorySideQueryService(chat_service=chat)

    result = service.retrieve(query="select positions", cards=_cards())

    assert result["status"] == "invalid_response"
    assert result["selected_names"] == []
    assert result["selected_memories"] == []
    assert result["memory_text"] == ""


def test_side_query_applies_selection_and_injection_budgets() -> None:
    cards = [
        {
            "name": f"memory-{index}",
            "description": f"memory {index}",
            "type": "user",
            "scope": "user",
            "content": "x" * 100,
        }
        for index in range(8)
    ]
    chat = FakeSelectorChatService(
        '{"selected_memories":['
        + ",".join(f'"memory-{index}"' for index in range(8))
        + "]}"
    )
    service = MemorySideQueryService(
        chat_service=chat,
        max_selected=3,
        max_item_chars=40,
        max_context_chars=70,
    )

    result = service.retrieve(query="current task", cards=cards)

    assert result["status"] == "selected"
    assert len(result["selected_names"]) == 3
    assert all(len(item["content"]) <= 40 for item in result["selected_memories"])
    assert len(result["memory_text"]) <= 70


class FakeAgentMemoryService:
    def build_memory_catalog(self) -> list[dict[str, Any]]:
        return _cards()


class FakeAgentChatClient:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, Any]]] = []

    def chat_completion_message(
        self,
        messages: list[dict[str, Any]],
        **_: Any,
    ) -> dict[str, Any]:
        self.messages.append([dict(message) for message in messages])
        return {"role": "assistant", "content": "done"}


class FakeAgentChatService:
    def __init__(self) -> None:
        self.client = FakeAgentChatClient()

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        return '{"selected_memories":["user-profile"]}'


def test_agent_runtime_injects_side_query_memory_without_transcript_message() -> None:
    chat = FakeAgentChatService()
    side_query = MemorySideQueryService(chat_service=chat)
    runtime = AgentRuntime(
        chat_service=chat,
        tools=ToolRegistry(),
        system_prompt="system",
        memory_service=FakeAgentMemoryService(),
        memory_side_query_service=side_query,
    )

    result = runtime.run(user_prompt="select Zhejiang law positions")

    assert result.answer == "done"
    assert "major=law" in chat.client.messages[0][1]["content"]
    assert len(chat.client.messages[0]) == 2
    assert any(event["event"] == "MemorySideQuery" for event in result.trace)


def test_load_memory_uses_side_query_result_instead_of_direct_memory_access() -> None:
    class ForbiddenDirectMemory:
        def get_long_term_context(self) -> dict[str, Any]:
            raise AssertionError("direct memory loading must not be used")

    registry = ToolRegistry()
    register_builtin_tools(registry)
    context = ToolContext(
        state={
            "memory_side_query": {
                "status": "selected",
                "selected_names": ["user-profile"],
                "selected_memories": _cards()[:1],
                "memory_text": "major=law; region=Zhejiang",
            }
        },
        memory_service=ForbiddenDirectMemory(),
    )

    result = registry.get("load_memory").handler({}, context)  # type: ignore[union-attr]

    assert result["status"] == "selected"
    assert result["count"] == 1
    assert result["items"]["memory_text"] == "major=law; region=Zhejiang"


def test_policy_state_does_not_read_direct_memory_context() -> None:
    class ForbiddenSessionService:
        def get_memory_context(self, **_: Any) -> dict[str, Any]:
            raise AssertionError("policy prompts must use side-query memory only")

    service = object.__new__(PolicyRagService)
    service.session_service = ForbiddenSessionService()
    service._load_side_query_memory = lambda **_: {
        "side_query_memory_text": "selected memory",
        "side_query_selected_names": ["user-profile"],
    }
    service._load_session_attachments = lambda **_: []
    service._node_route_intent = lambda _: {"need_rag": False}

    state = service.prepare_policy_state(
        query="current question",
        session_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )

    assert state["memory_context"]["side_query_memory_text"] == "selected memory"
