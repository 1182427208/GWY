from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class TraceEvent:
    event: str
    status: str = "done"
    step: str | None = None
    tool: str | None = None
    detail: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int | None = None
    turn: int | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event": self.event,
            "status": self.status,
            "step": self.step,
            "tool": self.tool,
            "detail": self.detail,
            "input": self.input,
            "output": self.output,
            "elapsed_ms": self.elapsed_ms,
            "turn": self.turn,
            "created_at": self.created_at,
        }


class TraceRecorder:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def add(self, event: TraceEvent) -> TraceEvent:
        self.events.append(event)
        return event

    def to_list(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]
