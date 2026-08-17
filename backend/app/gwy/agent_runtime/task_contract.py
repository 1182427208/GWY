from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TodoItem:
    content: str
    status: str = "pending"
    agent_type: str | None = None
    evidence_needed: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskContract:
    todos: list[TodoItem] = field(default_factory=list)
    objective: str | None = None
    owner: str | None = None
    notes: str | None = None

    @classmethod
    def from_todos(cls, todos: list[dict[str, Any]] | None) -> TaskContract:
        items: list[TodoItem] = []
        for raw in todos or []:
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content") or "").strip()
            if not content:
                continue
            status = str(raw.get("status") or "pending")
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            evidence_needed = [
                str(item).strip()
                for item in raw.get("evidence_needed") or []
                if str(item).strip()
            ]
            dependencies = [
                str(item).strip()
                for item in raw.get("dependencies") or []
                if str(item).strip()
            ]
            items.append(
                TodoItem(
                    content=content,
                    status=status,
                    agent_type=(
                        str(raw.get("agent_type") or "").strip() or None
                    ),
                    evidence_needed=evidence_needed,
                    dependencies=dependencies,
                )
            )
        return cls(todos=items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "owner": self.owner,
            "notes": self.notes,
            "todos": [
                {
                    "content": item.content,
                    "status": item.status,
                    "agent_type": item.agent_type,
                    "evidence_needed": list(item.evidence_needed),
                    "dependencies": list(item.dependencies),
                }
                for item in self.todos
            ],
        }


@dataclass(slots=True)
class ValidationResult:
    passed: bool = False
    missing_requirements: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    confidence: str = "low"
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "missing_requirements": list(self.missing_requirements),
            "next_actions": list(self.next_actions),
            "confidence": self.confidence,
            "detail": dict(self.detail),
        }
