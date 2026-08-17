from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolContext:
    state: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    memory_service: Any | None = None
    memory_side_query_service: Any | None = None

    def record_event(
        self,
        *,
        event: str,
        status: str = "done",
        step: str | None = None,
        tool: str | None = None,
        detail: str | None = None,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "event": event,
                "status": status,
                "step": step,
                "tool": tool,
                "detail": detail,
                "input": input or {},
                "output": output or {},
            }
        )


ToolHandler = Callable[[dict[str, Any], ToolContext], Any]


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)
