from __future__ import annotations

from typing import Any

from app.gwy.agent_runtime.mcp_tools import register_mcp_tools
from app.gwy.agent_runtime.skills import SkillRegistry
from app.gwy.agent_runtime.task_contract import TaskContract
from app.gwy.agent_runtime.tools import ToolContext, ToolRegistry, ToolSpec


def register_builtin_tools(registry: ToolRegistry) -> None:
    register_todo_tool(registry)
    register_skill_tool(registry)
    register_context_tools(registry)
    register_memory_tools(registry)
    register_mcp_tools(registry)


def register_todo_tool(registry: ToolRegistry) -> None:
    def todo_write(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        todos = args.get("todos")
        if not isinstance(todos, list):
            todos = []
        normalized: list[dict[str, str]] = []
        for item in todos:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            status = str(item.get("status") or "pending")
            if not content:
                continue
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            normalized.append({"content": content, "status": status})
        context.state["todos"] = normalized
        contract = TaskContract.from_todos(normalized)
        context.state["task_contract"] = contract.to_dict()
        return {"todos": normalized, "count": len(normalized), "task_contract": contract.to_dict()}

    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    }
    registry.register(
        ToolSpec(
            name="todo_tasks",
            description="Create or update the visible task plan before and during execution.",
            parameters=parameters,
            handler=todo_write,
        )
    )
    registry.register(
        ToolSpec(
            name="todo_write",
            description="Legacy alias for todo_tasks; create or update the visible task plan before and during execution.",
            parameters=parameters,
            handler=todo_write,
        )
    )


def register_skill_tool(registry: ToolRegistry) -> None:
    skill_registry = SkillRegistry()

    def load_skill(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        name = str(args.get("name") or "").strip()
        record = skill_registry.load(name)
        if record is None:
            available = list(skill_registry.skills)
            output = {
                "loaded": False,
                "name": name,
                "available": available,
                "summary": "Skill not found.",
            }
            context.record_event(
                event="SkillLoaded",
                status="error",
                step="load_skill",
                tool="load_skill",
                detail=f"Skill {name or '(empty)'} was not found.",
                input={"name": name},
                output=output,
            )
            return output

        loaded = dict(context.state.get("loaded_skills") or {})
        loaded[record.name] = {
            "description": record.description,
            "content": record.content,
        }
        context.state["loaded_skills"] = loaded
        output = {
            "loaded": True,
            "name": record.name,
            "description": record.description,
            "summary": record.content[:1200],
        }
        context.record_event(
            event="SkillLoaded",
            status="done",
            step=record.name,
            tool="load_skill",
            detail=f"Loaded runtime skill: {record.name}.",
            input={"name": name},
            output={
                "name": record.name,
                "description": record.description,
            },
        )
        return output

    registry.register(
        ToolSpec(
            name="load_skill",
            description=(
                "Load a runtime skill instruction into agent state before using "
                "a specialized workflow."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": list(skill_registry.skills) or ["position-planning"],
                    }
                },
                "required": ["name"],
            },
            handler=load_skill,
        )
    )


def register_context_tools(registry: ToolRegistry) -> None:
    def compact(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        focus = str(args.get("focus") or "").strip()
        output = {"compact_requested": True, "focus": focus}
        context.state["manual_compact_request"] = output
        context.record_event(
            event="Compact",
            status="running",
            step="manual_compact",
            tool="compact",
            detail="Manual context compression was requested.",
            output=output,
        )
        return output

    def compact_context(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        strategy = str(args.get("strategy") or "manual_checkpoint")
        note = str(args.get("note") or "").strip()
        checkpoints = list(context.state.get("compact_checkpoints") or [])
        checkpoint = {
            "strategy": strategy,
            "note": note,
            "state_keys": sorted(context.state.keys()),
        }
        checkpoints.append(checkpoint)
        context.state["compact_checkpoints"] = checkpoints
        context.record_event(
            event="Compact",
            status="done",
            step=strategy,
            tool="compact_context",
            detail=note or "Agent created a manual context checkpoint.",
            output=checkpoint,
        )
        return {
            "compacted": True,
            "strategy": strategy,
            "checkpoint_count": len(checkpoints),
        }

    registry.register(
        ToolSpec(
            name="compact_context",
            description="Create a visible context-compaction checkpoint for long agent runs.",
            parameters={
                "type": "object",
                "properties": {
                    "strategy": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
            handler=compact_context,
        )
    )
    registry.register(
        ToolSpec(
            name="compact",
            description="Trigger manual conversation compression with an optional focus.",
            parameters={
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "What to preserve in the continuity summary.",
                    }
                },
            },
            handler=compact,
        )
    )


def register_memory_tools(registry: ToolRegistry) -> None:
    def load_memory(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        scope = str(args.get("scope") or "session")
        memory_result = dict(context.state.get("memory_side_query") or {})
        if (
            not memory_result
            and context.memory_service is not None
            and context.memory_side_query_service is not None
        ):
            cards = context.memory_service.build_memory_catalog()
            memory_result = context.memory_side_query_service.retrieve(
                query=str(
                    args.get("query")
                    or context.state.get("query")
                    or ""
                ),
                cards=cards,
            )
            context.state["memory_side_query"] = memory_result
        memory = {
            "selected_memories": list(
                memory_result.get("selected_memories") or []
            ),
            "memory_text": str(memory_result.get("memory_text") or ""),
        }
        output = {
            "scope": scope,
            "items": memory,
            "count": len(memory.get("selected_memories") or []),
            "status": str(memory_result.get("status") or "empty"),
        }
        context.record_event(
            event="Memory",
            status="done",
            step="load",
            tool="load_memory",
            detail=(
                "Loaded memories selected by side-query "
                f"from {scope}."
            ),
            output=output,
        )
        return output

    def remember(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        key = str(args.get("key") or "").strip()
        value = str(args.get("value") or "").strip()
        if not key:
            return {"saved": False, "error": "key is required"}
        memory = dict(context.state.get("memory") or {})
        memory[key] = value
        context.state["memory"] = memory
        if context.memory_service is not None:
            try:
                context.memory_service.set_working_memory(key, {"value": value})
            except Exception:
                pass
        output = {"saved": True, "key": key, "value_preview": value[:200]}
        context.record_event(
            event="Memory",
            status="done",
            step="write",
            tool="remember",
            detail=f"Stored memory item: {key}.",
            input={"key": key},
            output=output,
        )
        return output

    registry.register(
        ToolSpec(
            name="load_memory",
            description="Load visible session memory before planning.",
            parameters={
                "type": "object",
                "properties": {"scope": {"type": "string"}},
            },
            handler=load_memory,
        )
    )
    registry.register(
        ToolSpec(
            name="remember",
            description="Store a short user preference or durable planning fact in runtime memory.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
            handler=remember,
        )
    )
