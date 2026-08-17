from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gwy.agent_runtime.task_contract import TaskContract, ValidationResult


@dataclass(slots=True)
class AgentResult:
    answer: str
    trace: list[dict[str, Any]]
    state: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    task_contract: TaskContract = field(default_factory=TaskContract)
    validation: ValidationResult = field(default_factory=ValidationResult)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "trace": list(self.trace),
            "state": dict(self.state),
            "messages": list(self.messages),
            "task_contract": self.task_contract.to_dict(),
            "validation": self.validation.to_dict(),
        }
