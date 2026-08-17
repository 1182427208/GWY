from __future__ import annotations

from app.gwy.agent_runtime import AgentRuntime, ToolRegistry
from app.gwy.agent_runtime import loop as runtime_loop
from app.gwy.agent_runtime.trace import TraceEvent, TraceRecorder


def test_hook_formats_subagent_and_web_events(monkeypatch) -> None:
    runtime = AgentRuntime(
        chat_service=object(),
        tools=ToolRegistry(),
        system_prompt="test",
    )
    recorder = TraceRecorder()
    lines: list[str] = []

    monkeypatch.setattr(runtime_loop.hook_logger, "info", lambda message, *args: lines.append(message % args if args else message))

    runtime._log_hook_event(
        TraceEvent(
            event="SubAgentStart",
            status="running",
            step="search_positions_pg",
            tool="PositionDecisionAgent",
            detail="PositionDecisionAgent started from search_positions_pg.",
            input={"query": "岗位推荐", "top_k": 5},
        ),
        recorder,
    )
    runtime._log_hook_event(
        TraceEvent(
            event="SubAgentToolUse",
            status="done",
            step="retrieve_position_history",
            tool="PositionDecisionAgent",
            detail="Retrieved position history and competition signals.",
            input={"query": "岗位推荐"},
            output={"history_count": 3},
        ),
        recorder,
    )
    runtime._log_hook_event(
        TraceEvent(
            event="WebResearchStep",
            status="done",
            step="web_browser_fallback",
            tool="WebResearchService",
            detail="Browser fallback was needed for dynamic page content.",
            input={"url": "https://www.gov.cn/"},
            output={"browser_fallback_count": 1, "citation_count": 2},
            ),
            recorder,
        )
    joined = "\n".join(lines)

    assert "SubAgentStart/PositionDecisionAgent" in joined
    assert "SubAgentToolUse/PositionDecisionAgent" in joined
    assert "WebResearchStep/WebResearchService" in joined
    assert "browser_fallback_count" in joined


def test_hook_renders_todo_tasks_summary(monkeypatch) -> None:
    runtime = AgentRuntime(
        chat_service=object(),
        tools=ToolRegistry(),
        system_prompt="test",
    )
    recorder = TraceRecorder()
    lines: list[str] = []

    monkeypatch.setattr(runtime_loop.hook_logger, "info", lambda message, *args: lines.append(message % args if args else message))

    runtime._log_hook_event(
        TraceEvent(
            event="PostToolUse",
            status="done",
            step="todo_tasks",
            tool="todo_tasks",
            output={
                "todos": [
                    {"content": "先筛岗位", "status": "completed"},
                    {"content": "再补证据", "status": "in_progress"},
                ]
            },
        ),
        recorder,
    )
    joined = "\n".join(lines)

    assert "Current Tasks" in joined
    assert "先筛岗位" in joined
    assert "再补证据" in joined


def test_hook_shows_loaded_skill_name(monkeypatch) -> None:
    runtime = AgentRuntime(
        chat_service=object(),
        tools=ToolRegistry(),
        system_prompt="test",
    )
    recorder = TraceRecorder()
    lines: list[str] = []

    monkeypatch.setattr(runtime_loop.hook_logger, "info", lambda message, *args: lines.append(message % args if args else message))

    runtime._log_hook_event(
        TraceEvent(
            event="SkillLoaded",
            status="done",
            step="position-planning",
            tool="load_skill",
            detail="Loaded runtime skill: position-planning.",
            input={"name": "position-planning"},
            output={"name": "position-planning", "description": "Plan civil-service position recommendation."},
        ),
        recorder,
    )

    joined = "\n".join(lines)
    assert "SkillLoaded/position-planning" in joined
    assert "Loaded runtime skill" in joined
