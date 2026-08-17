from __future__ import annotations

from app.gwy.agent_runtime import AgentRuntime, ToolContext, ToolRegistry, ToolSpec
from app.gwy.agent_runtime import loop as runtime_loop
from app.gwy.agent_runtime.trace import TraceRecorder


def _build_runtime() -> AgentRuntime:
    return AgentRuntime(
        chat_service=object(),
        tools=ToolRegistry(),
        system_prompt="test",
        max_turns=1,
    )


def test_validation_gate_flags_partial_results(monkeypatch) -> None:
    runtime = _build_runtime()
    lines: list[str] = []
    recorder = TraceRecorder()

    monkeypatch.setattr(
        runtime_loop.hook_logger,
        "info",
        lambda message, *args: lines.append(message % args if args else message),
    )

    runtime.tools.register(
        ToolSpec(
            name="web_search",
            description="Search web content.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _args, _context: {
                "status": "partial",
                "need_more_info": True,
                "summary": "incomplete evidence",
            },
        )
    )
    messages: list[dict[str, object]] = []
    context = ToolContext(state={})

    def emit(event):
        recorder.add(event)
        runtime._log_hook_event(event, recorder)

    runtime._run_tool_call(
        call={"id": "call_1", "function": {"name": "web_search", "arguments": "{}"}},
        messages=messages,
        tool_context=context,
        turn=1,
        emit=emit,
    )

    assert context.state["runtime_validation_failed"] is True
    assert context.state["runtime_validation_gates"][0]["status"] == "failed"
    assert context.state["runtime_validation_gates"][0]["reason"] == "tool reported partial"
    assert messages[-1]["role"] == "tool"
    assert "ValidationGate/web_search" in "\n".join(lines)


def test_validation_gate_passes_on_complete_result() -> None:
    runtime = _build_runtime()
    runtime.tools.register(
        ToolSpec(
            name="web_search",
            description="Search web content.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _args, _context: {
                "status": "ok",
                "result": "complete evidence",
            },
        )
    )
    messages: list[dict[str, object]] = []
    context = ToolContext(state={})
    recorder = TraceRecorder()

    def emit(event):
        recorder.add(event)
        runtime._log_hook_event(event, recorder)

    runtime._run_tool_call(
        call={"id": "call_1", "function": {"name": "web_search", "arguments": "{}"}},
        messages=messages,
        tool_context=context,
        turn=1,
        emit=emit,
    )

    assert context.state.get("runtime_validation_failed") is not True
    assert context.state["runtime_validation_gates"][0]["status"] == "passed"


def test_validation_gate_blocks_unregistered_tool() -> None:
    runtime = _build_runtime()
    messages: list[dict[str, object]] = []
    context = ToolContext(state={})
    recorder = TraceRecorder()

    def emit(event):
        recorder.add(event)
        runtime._log_hook_event(event, recorder)

    runtime._run_tool_call(
        call={"id": "call_1", "function": {"name": "nonexistent_tool", "arguments": "{}"}},
        messages=messages,
        tool_context=context,
        turn=1,
        emit=emit,
    )

    assert context.state["runtime_validation_failed"] is True
    assert context.state["runtime_validation_gates"][0]["reason"] == "permission:nonexistent_tool is not registered in the web agent runtime."
    assert messages[-1]["role"] == "tool"
