from __future__ import annotations

from app.gwy.agent_runtime import ToolContext, ToolRegistry
from app.gwy.agent_runtime.builtin_tools import register_builtin_tools
from app.gwy.agent_runtime.result import AgentResult
from app.gwy.agent_runtime.task_contract import TaskContract, ValidationResult


def test_todo_tasks_and_todo_write_share_structured_task_contract() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    todo_tasks = registry.get("todo_tasks")
    tool = registry.get("todo_write")
    assert todo_tasks is not None
    assert tool is not None
    assert todo_tasks.handler is tool.handler

    context = ToolContext(state={})
    output = todo_tasks.handler(
        {
            "todos": [
                {"content": "先做岗位筛选", "status": "pending"},
                {"content": "再做证据核验", "status": "in_progress"},
            ]
        },
        context,
    )

    assert output["count"] == 2
    assert context.state["task_contract"]["todos"][0]["content"] == "先做岗位筛选"
    assert context.state["task_contract"]["todos"][1]["status"] == "in_progress"


def test_agent_result_carries_task_contract_and_validation() -> None:
    contract = TaskContract.from_todos(
        [
            {"content": "先规划", "status": "pending"},
            {"content": "再执行", "status": "completed"},
        ]
    )
    validation = ValidationResult(
        passed=True,
        missing_requirements=[],
        next_actions=[],
        confidence="high",
    )
    result = AgentResult(
        answer="ok",
        trace=[],
        state={},
        task_contract=contract,
        validation=validation,
    )

    payload = result.to_dict()

    assert payload["task_contract"]["todos"][0]["content"] == "先规划"
    assert payload["validation"]["passed"] is True
