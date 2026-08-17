# GwyPilot Agent Loop V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 GwyPilot Agent Loop 收敛为“主 Agent 负责规划与调度、子 Agent 负责单域 ReAct + Reflection、验证层负责判定完成”的稳定架构，同时保持工具调用、权限控制、异常恢复和评测入口不变。

**Architecture:** 保留 `AgentRuntime` 作为通用执行壳，补一层显式任务契约和路由协议，让主 Agent 先产出 `todo_write` 计划，再把单域任务交给职责更窄的子 Agent。子 Agent 继续复用现有工具与权限，但内部不再依赖硬编码的 LangGraph 步骤链，而是改成“根据任务自主决定怎么查、查什么、查够没”的 ReAct + Reflection 执行方式。最终输出统一回到结构化 `AgentResult` / `Trace` / `Artifact`，并把验证结果送回主循环决定继续、重规划或结束。

**Tech Stack:** FastAPI, SQLModel, PostgreSQL, Milvus, LangGraph（保留现有兼容点）, Pydantic, Pytest, existing GwyPilot agent runtime.

---

### Task 1: 引入统一任务契约和子 Agent 输出协议

**Files:**
- Create: `backend/app/gwy/agent_runtime/task_contract.py`
- Create: `backend/app/gwy/agent_runtime/result.py`
- Modify: `backend/app/gwy/agent_runtime/builtin_tools.py`
- Modify: `backend/app/gwy/agent_runtime/loop.py`
- Test: `backend/tests/gwy/test_agent_runtime_task_contract.py`

- [ ] **Step 1: Write the failing test**

```python
from app.gwy.agent_runtime.result import AgentResult
from app.gwy.agent_runtime.task_contract import TaskContract, TodoItem


def test_task_contract_normalizes_todos_and_result_payload() -> None:
    contract = TaskContract.from_todos(
        [
            {"content": "先查岗位硬性条件", "status": "pending"},
            {"content": "再查政策证据", "status": "in_progress"},
        ]
    )

    result = AgentResult(
        status="partial",
        answer="需要补充证据",
        task_contract=contract,
        trace=[],
        state={},
    )

    assert result.task_contract.todos[0].content == "先查岗位硬性条件"
    assert result.status == "partial"
    assert result.answer == "需要补充证据"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_agent_runtime_task_contract.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing symbol errors.

- [ ] **Step 3: Write minimal implementation**

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TodoItem:
    content: str
    status: str = "pending"
    agent_type: str | None = None
    evidence_needed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskContract:
    todos: list[TodoItem] = field(default_factory=list)

    @classmethod
    def from_todos(cls, todos: list[dict[str, Any]]) -> "TaskContract":
        items: list[TodoItem] = []
        for raw in todos:
            content = str(raw.get("content") or "").strip()
            if not content:
                continue
            status = str(raw.get("status") or "pending")
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            items.append(TodoItem(content=content, status=status))
        return cls(todos=items)


@dataclass(slots=True)
class AgentResult:
    status: str
    answer: str
    task_contract: TaskContract = field(default_factory=TaskContract)
    trace: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_agent_runtime_task_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/agent_runtime/task_contract.py backend/app/gwy/agent_runtime/result.py backend/app/gwy/agent_runtime/builtin_tools.py backend/app/gwy/agent_runtime/loop.py backend/tests/gwy/test_agent_runtime_task_contract.py
git commit -m "feat: add structured agent task contract"
```

### Task 2: 把主 Agent 调度层改成“先规划、再分配、再验证”

**Files:**
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
- Modify: `backend/app/gwy/services/position_snapshot_runtime_service.py`
- Modify: `backend/app/gwy/agent_runtime/permissions.py`
- Modify: `backend/app/gwy/agent_runtime/loop.py`
- Test: `backend/tests/gwy/test_agent_runtime_plan_route.py`

- [ ] **Step 1: Write the failing test**

```python
def test_runtime_emits_todo_before_domain_tools_and_keeps_validation_state() -> None:
    ...
    assert trace[0]["tool"] == "todo_write"
    assert result["state"]["task_contract"]["todos"]
    assert result["state"]["validation"]["passed"] in {True, False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_agent_runtime_plan_route.py -v`
Expected: FAIL because the runtime does not yet persist structured planning and validation state.

- [ ] **Step 3: Write minimal implementation**

```python
class AutonomousChatAgentService:
    def _build_runtime_context(self, *, query: str, ...) -> dict[str, Any]:
        return {
            "query": query,
            "task_contract": {"todos": []},
            "validation": {"passed": False, "missing_requirements": []},
            ...
        }

    def _finalize_state(self, state: dict[str, Any], trace: list[dict[str, Any]]) -> None:
        state["task_contract"] = dict(state.get("task_contract") or {})
        state["validation"] = dict(state.get("validation") or {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_agent_runtime_plan_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/autonomous_chat_agent_service.py backend/app/gwy/services/position_snapshot_runtime_service.py backend/app/gwy/agent_runtime/permissions.py backend/app/gwy/agent_runtime/loop.py backend/tests/gwy/test_agent_runtime_plan_route.py
git commit -m "feat: route agent loop through explicit planning and validation"
```

### Task 3: 收敛子 Agent 职责，保留 ReAct + Reflection，去掉硬编码步骤链

**Files:**
- Modify: `backend/app/gwy/agents/position_decision_agent.py`
- Modify: `backend/app/gwy/agents/policy_evidence_agent.py`
- Modify: `backend/app/gwy/agents/study_plan_agent.py`
- Modify: `backend/app/gwy/agents/report_generator_agent.py`
- Test: `backend/tests/gwy/test_agent_loop_subagents.py`

- [ ] **Step 1: Write the failing test**

```python
def test_subagents_return_structured_state_without_fixed_step_indexing() -> None:
    ...
    assert "plan_phases" not in result["trace_steps"]
    assert result["status"] in {"completed", "partial"}
    assert result["reflection"]["missing_evidence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_agent_loop_subagents.py -v`
Expected: FAIL because the current agents still expose fixed node pipelines rather than a unified structured state.

- [ ] **Step 3: Write minimal implementation**

```python
class BaseReactReflectionAgent:
    def run(self, *, task: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan(task)
        observation = self._observe(task, plan)
        reflection = self._reflect(task, plan, observation)
        return {
            "status": reflection.get("status", "completed"),
            "answer": reflection.get("answer", ""),
            "trace": [...],
            "task_contract": plan,
            "reflection": reflection,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_agent_loop_subagents.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/agents/position_decision_agent.py backend/app/gwy/agents/policy_evidence_agent.py backend/app/gwy/agents/study_plan_agent.py backend/app/gwy/agents/report_generator_agent.py backend/tests/gwy/test_agent_loop_subagents.py
git commit -m "feat: narrow subagent responsibilities"
```

### Task 4: 扩展评测与回归测试，覆盖 planning、validation、artifact 质量

**Files:**
- Modify: `backend/app/gwy/evals/adapters/agent_adapter.py`
- Modify: `backend/app/gwy/evals/schemas.py`
- Modify: `backend/app/gwy/evals/scorers/*.py`
- Test: `backend/tests/gwy/evals/test_online_evaluation.py`
- Test: `backend/tests/gwy/evals/test_eval_scorers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_agent_observation_includes_planning_and_validation_fields() -> None:
    observation = normalize_agent_output(
        {"answer": "ok", "state": {"task_contract": {"todos": []}, "validation": {"passed": True}}}
    )
    assert observation.raw_output["state"]["validation"]["passed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/evals/test_eval_scorers.py backend/tests/gwy/evals/test_online_evaluation.py -v`
Expected: FAIL until the adapter/scorer schema recognizes planning and validation fields.

- [ ] **Step 3: Write minimal implementation**

```python
def normalize_agent_output(output: Any) -> AgentObservation:
    ...
    return AgentObservation(
        ...
        raw_output=payload,
        trace=trace,
        task_contract=_as_mapping(payload.get("task_contract") or state.get("task_contract")),
        validation=_as_mapping(payload.get("validation") or state.get("validation")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/evals/test_eval_scorers.py backend/tests/gwy/evals/test_online_evaluation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/evals/adapters/agent_adapter.py backend/app/gwy/evals/schemas.py backend/app/gwy/evals/scorers backend/tests/gwy/evals/test_online_evaluation.py backend/tests/gwy/evals/test_eval_scorers.py
git commit -m "feat: extend evals for planner and validation signals"
```

### Self-Review Checklist

- [ ] All tasks map back to the V2 spec: planning, subagent narrowing, validation gate, structured artifacts, eval extension.
- [ ] No step changes tool permissions, destructive tools, or external behavior outside the agent loop.
- [ ] No placeholder text remains in the plan.
- [ ] Exact file paths and test commands are listed.

