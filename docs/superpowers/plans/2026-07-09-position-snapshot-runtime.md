# 快照驱动岗位推荐 AgentRuntime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让聊天岗位推荐和岗位分析任务统一走“固定快照 + AgentRuntime”的岗位推荐与报告分析流程。

**Architecture:** 新增 `PositionSnapshotRuntimeService` 作为快照岗位分析主流程，内部复用 `AgentRuntime` 和现有岗位、政策、风险、复习计划能力。`PositionAnalysisService` 优先调用新 runtime，失败时 fallback 到旧 `PositionAnalysisAgent`；聊天入口没有快照时只引导用户固定快照，有快照时复用同一服务。

**Tech Stack:** FastAPI, SQLModel, Pytest, LangGraph existing agents, existing OpenAI-compatible `AgentRuntime`, PostgreSQL-backed position catalog, Milvus policy evidence.

## Global Constraints

- 不新增前端页面。
- 不用 RAG 替代 PostgreSQL 的结构化岗位筛选。
- 不立即删除现有 `PositionAnalysisAgent`；新 runtime 稳定前保留为 fallback。
- 不改变 `full-stack-fastapi-template` 的原有项目骨架和启动方式。
- 新代码优先放在 `backend/app/gwy/`。
- 职位表筛选必须依赖 PostgreSQL，政策、报考指南、专业目录仍走 Milvus。

---

## File Structure

- Create: `backend/app/gwy/services/position_snapshot_runtime_service.py`
  - 负责构建快照岗位分析 runtime、注册工具、运行并返回兼容 `PositionAnalysisService` 的结果。
- Modify: `backend/app/gwy/services/position_analysis_service.py`
  - 注入并优先调用 `PositionSnapshotRuntimeService`，runtime 失败时 fallback 到旧 `PositionAnalysisAgent`。
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
  - 岗位推荐无快照时返回固定快照引导；有快照上下文时调用快照 runtime。
- Modify: `backend/app/api/routes/gwy.py`
  - 如现有请求体没有快照上下文字段，补最小字段或从 session state 取 snapshot/task id；不新增页面。
- Create: `backend/tests/gwy/test_position_snapshot_runtime_service.py`
  - 单测 runtime 工具注册、输出形状、fallback 友好性。
- Modify: `backend/tests/gwy/test_position_analysis_agent.py` or create `backend/tests/gwy/test_position_analysis_runtime_integration.py`
  - 验证 `PositionAnalysisService` 优先 runtime、失败 fallback。
- Modify: `backend/tests/gwy/test_explicit_position_mode.py` or create `backend/tests/gwy/test_autonomous_position_snapshot_gate.py`
  - 验证聊天岗位推荐无快照时不跑 PG 推荐，只返回固定快照引导。

---

### Task 1: 新增快照 Runtime 服务骨架

**Files:**
- Create: `backend/app/gwy/services/position_snapshot_runtime_service.py`
- Test: `backend/tests/gwy/test_position_snapshot_runtime_service.py`

**Interfaces:**
- Produces: `PositionSnapshotRuntimeService.run(snapshot, user_id, task_id=None, user_profile=None, recommendation_context=None) -> dict[str, Any]`
- Produces: result keys `status`, `stage`, `report`, `trace`, `output_json`, `recommendations`, `risk_review`, `needs_more_info`, `missing_fields`, `clarifying_questions`.

- [ ] **Step 1: Write failing test for result shape**

```python
from uuid import uuid4

from app.gwy.services.position_snapshot_runtime_service import (
    PositionSnapshotRuntimeService,
)


class FakeRuntime:
    def __init__(self, result):
        self.result = result

    def run(self, *, user_prompt, context):
        return self.result


class RuntimeResult:
    answer = "# 岗位分析报告\n\n模型生成内容"
    trace = [{"event": "Stop", "status": "done", "step": "agent_loop"}]
    state = {
        "recommendations": [{"position_id": "p1", "job_title": "综合管理"}],
        "risk_review": {"risk_level": "low"},
        "report": "# 岗位分析报告\n\n模型生成内容",
    }
    messages = []


def test_snapshot_runtime_returns_position_analysis_shape():
    service = PositionSnapshotRuntimeService(
        session=None,
        runtime_factory=lambda **kwargs: FakeRuntime(RuntimeResult()),
    )

    result = service.run(
        snapshot={
            "title": "测试快照",
            "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
            "filters_json": {"year": 2026, "exam_type": "national"},
        },
        user_id=uuid4(),
        user_profile={"major": "法学", "education": "本科"},
    )

    assert result["status"] == "completed"
    assert result["stage"] == "position_snapshot_runtime"
    assert "岗位分析报告" in result["report"]
    assert result["recommendations"][0]["job_title"] == "综合管理"
    assert result["risk_review"]["risk_level"] == "low"
    assert result["output_json"]["runtime_state"]["risk_review"]["risk_level"] == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/gwy/test_position_snapshot_runtime_service.py::test_snapshot_runtime_returns_position_analysis_shape -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.gwy.services.position_snapshot_runtime_service'`.

- [ ] **Step 3: Implement minimal service skeleton**

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.gwy.agent_runtime import AgentRuntimeResult


class PositionSnapshotRuntimeService:
    def __init__(
        self,
        *,
        session: Session | None,
        runtime_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.session = session
        self.runtime_factory = runtime_factory

    def run(
        self,
        *,
        snapshot: dict[str, Any],
        user_id: UUID | str,
        task_id: UUID | str | None = None,
        user_profile: dict[str, Any] | None = None,
        recommendation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = {
            "snapshot": dict(snapshot or {}),
            "user_id": str(user_id),
            "task_id": str(task_id) if task_id else None,
            "user_profile": dict(user_profile or {}),
            "recommendation_context": dict(recommendation_context or {}),
        }
        runtime = self._build_runtime()
        runtime_result = runtime.run(
            user_prompt=self._build_user_prompt(context),
            context=context,
        )
        return self._serialize_runtime_result(runtime_result)

    def _build_runtime(self) -> Any:
        if self.runtime_factory is None:
            raise RuntimeError("runtime_factory is required until runtime tools are implemented.")
        return self.runtime_factory()

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        snapshot = dict(context.get("snapshot") or {})
        return f"请基于固定岗位快照生成岗位分析报告：{snapshot.get('title') or '岗位快照'}"

    def _serialize_runtime_result(self, result: AgentRuntimeResult | Any) -> dict[str, Any]:
        state = dict(getattr(result, "state", {}) or {})
        report = str(state.get("report") or getattr(result, "answer", "") or "")
        trace = list(getattr(result, "trace", []) or [])
        return {
            "status": "completed",
            "stage": "position_snapshot_runtime",
            "report": report,
            "trace": trace,
            "output_json": {
                "runtime_state": state,
                "agent_journey": trace,
                "trace_count": len(trace),
            },
            "recommendations": list(state.get("recommendations") or []),
            "risk_review": dict(state.get("risk_review") or {}),
            "needs_more_info": bool(state.get("needs_more_info", False)),
            "missing_fields": list(state.get("missing_fields") or []),
            "clarifying_questions": list(state.get("clarifying_questions") or []),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/gwy/test_position_snapshot_runtime_service.py::test_snapshot_runtime_returns_position_analysis_shape -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/position_snapshot_runtime_service.py backend/tests/gwy/test_position_snapshot_runtime_service.py
git commit -m "feat: add position snapshot runtime service skeleton"
```

---

### Task 2: 注册快照分析 Runtime 工具

**Files:**
- Modify: `backend/app/gwy/services/position_snapshot_runtime_service.py`
- Test: `backend/tests/gwy/test_position_snapshot_runtime_service.py`

**Interfaces:**
- Produces: `_build_tool_registry() -> ToolRegistry`
- Produces tools `load_snapshot`, `analyze_snapshot_positions`, `review_position_risks`, `generate_study_plan`, `compose_snapshot_report`.

- [ ] **Step 1: Add failing test for tool-driven runtime state**

```python
def test_snapshot_runtime_registers_position_tools():
    service = PositionSnapshotRuntimeService(session=None)
    registry = service._build_tool_registry()

    names = set(registry.schemas()[i]["function"]["name"] for i in range(len(registry.schemas())))

    assert "todo_write" in names
    assert "load_snapshot" in names
    assert "analyze_snapshot_positions" in names
    assert "review_position_risks" in names
    assert "generate_study_plan" in names
    assert "compose_snapshot_report" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/gwy/test_position_snapshot_runtime_service.py::test_snapshot_runtime_registers_position_tools -v`

Expected: FAIL with `AttributeError: 'PositionSnapshotRuntimeService' object has no attribute '_build_tool_registry'`.

- [ ] **Step 3: Implement registry and minimal handlers**

Add imports:

```python
from app.gwy.agent_runtime import ToolContext, ToolRegistry, ToolSpec
from app.gwy.agent_runtime.builtin_tools import register_builtin_tools
```

Add methods:

```python
    def _build_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_builtin_tools(registry)
        registry.register(ToolSpec(
            name="load_snapshot",
            description="加载固定岗位快照并写入 runtime state。",
            parameters={"type": "object", "properties": {}},
            handler=self._tool_load_snapshot,
        ))
        registry.register(ToolSpec(
            name="analyze_snapshot_positions",
            description="基于 PostgreSQL 岗位表分析快照中的岗位。",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=self._tool_analyze_snapshot_positions,
        ))
        registry.register(ToolSpec(
            name="review_position_risks",
            description="复核当前推荐岗位的资格和政策风险。",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=self._tool_review_position_risks,
        ))
        registry.register(ToolSpec(
            name="generate_study_plan",
            description="根据用户画像和推荐岗位生成复习计划。",
            parameters={"type": "object", "properties": {"study_hours_per_day": {"type": "integer"}}},
            handler=self._tool_generate_study_plan,
        ))
        registry.register(ToolSpec(
            name="compose_snapshot_report",
            description="基于快照事实、风险复核和复习计划生成最终 Markdown 报告。",
            parameters={"type": "object", "properties": {"title": {"type": "string"}}},
            handler=self._tool_compose_snapshot_report,
        ))
        return registry

    def _tool_load_snapshot(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        snapshot = dict(context.state.get("snapshot") or {})
        summary = {
            "title": snapshot.get("title"),
            "selected_position_ids": list(snapshot.get("selected_position_ids") or []),
            "filters_json": dict(snapshot.get("filters_json") or {}),
            "notes": snapshot.get("notes") or "",
        }
        context.state["snapshot_summary"] = summary
        return summary

    def _tool_analyze_snapshot_positions(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        context.state.setdefault("recommendations", [])
        context.state.setdefault("position_facts", {"summary": {}, "recommendations": []})
        return context.state["position_facts"]

    def _tool_review_position_risks(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        context.state["risk_review"] = {"risk_level": "low", "risk_items": []}
        return context.state["risk_review"]

    def _tool_generate_study_plan(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        context.state["study_plan"] = {"status": "skipped"}
        context.state["study_plan_markdown"] = ""
        return context.state["study_plan"]

    def _tool_compose_snapshot_report(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        title = str(args.get("title") or "岗位推荐分析报告")
        recommendations = list(context.state.get("recommendations") or [])
        lines = [f"# {title}", "", "## 分析计划与结论", "", f"- 已分析岗位数量：{len(recommendations)}"]
        report = "\n".join(lines)
        context.state["report"] = report
        return {"report": report}
```

Change `_build_runtime` to use the registry when no factory is provided:

```python
    def _build_runtime(self) -> Any:
        if self.runtime_factory is not None:
            return self.runtime_factory()
        from app.gwy.agent_runtime import AgentRuntime
        from app.gwy.llm.chat_service import ChatService

        return AgentRuntime(
            chat_service=ChatService(),
            tools=self._build_tool_registry(),
            system_prompt=POSITION_SNAPSHOT_SYSTEM_PROMPT,
            max_turns=12,
            temperature=0.2,
        )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/gwy/test_position_snapshot_runtime_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/position_snapshot_runtime_service.py backend/tests/gwy/test_position_snapshot_runtime_service.py
git commit -m "feat: register snapshot runtime tools"
```

---

### Task 3: 接入真实岗位、风险、复习计划和报告能力

**Files:**
- Modify: `backend/app/gwy/services/position_snapshot_runtime_service.py`
- Test: `backend/tests/gwy/test_position_snapshot_runtime_service.py`

**Interfaces:**
- Consumes: existing `PositionCatalogService.analyze_positions(...)`
- Consumes: existing `RiskReviewAgent.run(...)`
- Consumes: existing `StudyPlanService.generate(...)`
- Consumes: existing `ReportGeneratorAgent.run(...)`

- [ ] **Step 1: Add failing test with fake collaborators**

```python
class FakeCatalog:
    def analyze_positions(self, *, position_ids, query, profile, top_k):
        return {
            "summary": {"recommendation_count": 1},
            "recommendations": [{"position_id": "p1", "job_title": "综合管理"}],
            "selected_positions": [{"position_id": "p1", "job_title": "综合管理"}],
            "retrieval_trace": [{"step": "pg", "status": "done"}],
        }


class FakeRisk:
    def run(self, *, query, recommendations):
        return {"risk_level": "low", "risk_items": [], "trace": []}


class FakeStudy:
    def generate(self, **kwargs):
        return {"markdown": "# 复习计划", "plan": {"title": "计划"}}


class FakeReport:
    def run(self, *, title, recommendations, risk_review):
        return {"report": "# 深度岗位报告\n\n- 综合管理", "report_meta": {"used_llm": False}, "trace": []}


def test_snapshot_tools_use_real_collaborator_contracts():
    service = PositionSnapshotRuntimeService(
        session=None,
        position_catalog_service=FakeCatalog(),
        risk_review_agent=FakeRisk(),
        study_plan_service_factory=lambda session: FakeStudy(),
        report_generator_agent=FakeReport(),
    )
    context = ToolContext(state={
        "snapshot": {
            "title": "测试快照",
            "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
            "filters_json": {"year": 2026, "exam_type": "national"},
        },
        "user_profile": {"major": "法学"},
        "user_id": str(uuid4()),
    })

    facts = service._tool_analyze_snapshot_positions({"query": "法学岗位"}, context)
    risk = service._tool_review_position_risks({"query": "法学岗位"}, context)
    plan = service._tool_generate_study_plan({"study_hours_per_day": 4}, context)
    report = service._tool_compose_snapshot_report({"title": "测试报告"}, context)

    assert facts["recommendations"][0]["job_title"] == "综合管理"
    assert risk["risk_level"] == "low"
    assert plan["markdown"] == "# 复习计划"
    assert "深度岗位报告" in report["report"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/gwy/test_position_snapshot_runtime_service.py::test_snapshot_tools_use_real_collaborator_contracts -v`

Expected: FAIL because constructor dependencies and handlers are not wired.

- [ ] **Step 3: Wire collaborators**

Update `__init__` to accept optional collaborators:

```python
        position_catalog_service: Any | None = None,
        risk_review_agent: Any | None = None,
        study_plan_service_factory: Callable[[Session | None], Any] | None = None,
        report_generator_agent: Any | None = None,
        chat_service: Any | None = None,
```

Initialize defaults using existing classes when not provided and `session` is available.

Update handlers:

```python
    def _tool_analyze_snapshot_positions(self, args, context):
        snapshot = dict(context.state.get("snapshot") or {})
        selected_ids = list(snapshot.get("selected_position_ids") or [])
        query = str(args.get("query") or snapshot.get("title") or context.state.get("query") or "")
        profile = dict(context.state.get("user_profile") or {})
        result = self.position_catalog_service.analyze_positions(
            position_ids=selected_ids,
            query=query,
            profile=profile,
            top_k=max(1, len(selected_ids) or int(context.state.get("top_k") or 5)),
        )
        context.state["position_facts"] = dict(result)
        context.state["recommendations"] = list(result.get("recommendations") or [])
        return dict(result)
```

Use the same pattern for risk, study plan, and report generation. `generate_study_plan` must call `StudyPlanService.generate(..., push_to_feishu=False)` when task persistence is needed from analysis.

- [ ] **Step 4: Run service tests**

Run: `cd backend && pytest tests/gwy/test_position_snapshot_runtime_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/position_snapshot_runtime_service.py backend/tests/gwy/test_position_snapshot_runtime_service.py
git commit -m "feat: wire snapshot runtime collaborators"
```

---

### Task 4: 岗位分析任务优先调用 Runtime，并保留 fallback

**Files:**
- Modify: `backend/app/gwy/services/position_analysis_service.py`
- Test: `backend/tests/gwy/test_position_analysis_runtime_integration.py`

**Interfaces:**
- Consumes: `PositionSnapshotRuntimeService.run(...) -> dict[str, Any]`
- Produces: existing `PositionAnalysisService._execute_task(...)` behavior remains compatible.

- [ ] **Step 1: Add failing tests for runtime-first and fallback**

```python
def test_position_analysis_service_uses_snapshot_runtime(monkeypatch, db):
    called = {"runtime": False, "legacy": False}

    class FakeRuntimeService:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            called["runtime"] = True
            return {
                "status": "completed",
                "stage": "position_snapshot_runtime",
                "report": "# Runtime 报告",
                "trace": [{"event": "Stop", "step": "agent_loop", "status": "done"}],
                "output_json": {"recommendations": []},
                "recommendations": [],
            }

    class FakeLegacyAgent:
        def run(self, **kwargs):
            called["legacy"] = True
            return {"status": "completed", "report": "# Legacy 报告", "trace": [], "output_json": {}}

    service = PositionAnalysisService(
        session=db,
        agent=FakeLegacyAgent(),
        snapshot_runtime_service_factory=lambda **kwargs: FakeRuntimeService(),
        feishu_push_agent=None,
    )

    prepared = service.create_task(snapshot={"title": "测试", "snapshot_json": {}}, user_id=existing_user_id)
    result = service.execute_existing_task(
        snapshot_id=prepared["snapshot_id"],
        task_id=prepared["task_id"],
        user_id=existing_user_id,
    )

    assert called["runtime"] is True
    assert called["legacy"] is False
    assert result["report"] == "# Runtime 报告"
```

Add a second test where `FakeRuntimeService.run` raises and assert legacy is called.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/gwy/test_position_analysis_runtime_integration.py -v`

Expected: FAIL because `snapshot_runtime_service_factory` is not supported.

- [ ] **Step 3: Implement runtime-first call**

Add constructor parameter:

```python
        snapshot_runtime_service_factory: Callable[..., Any] | None = None,
```

Store it:

```python
        self.snapshot_runtime_service_factory = snapshot_runtime_service_factory
```

Replace direct `self.agent.run(...)` in `_execute_task` with:

```python
        try:
            result = self._run_snapshot_runtime_analysis(
                snapshot_row=snapshot_row,
                task_row=task_row,
                user_uuid=user_uuid,
                user_profile=enriched_profile,
                recommendation_context=recommendation_context,
            )
        except Exception:
            logger.exception("Snapshot runtime failed; falling back to legacy position analysis agent")
            result = self.agent.run(
                snapshot_id=snapshot_row.id,
                user_id=user_uuid,
                task_id=task_row.id,
                user_profile=enriched_profile,
                recommendation_context=recommendation_context,
            )
            result["trace"] = [
                {
                    "step": "snapshot_runtime_fallback",
                    "status": "done",
                    "detail": "Snapshot AgentRuntime failed; legacy PositionAnalysisAgent completed the task.",
                },
                *list(result.get("trace") or []),
            ]
```

Add `_run_snapshot_runtime_analysis` to instantiate `PositionSnapshotRuntimeService`.

- [ ] **Step 4: Run integration tests**

Run: `cd backend && pytest tests/gwy/test_position_analysis_runtime_integration.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/position_analysis_service.py backend/tests/gwy/test_position_analysis_runtime_integration.py
git commit -m "feat: use snapshot runtime for position analysis"
```

---

### Task 5: 聊天岗位推荐改为快照门禁

**Files:**
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
- Modify if needed: `backend/app/api/routes/gwy.py`
- Test: `backend/tests/gwy/test_autonomous_position_snapshot_gate.py`

**Interfaces:**
- Produces: `_has_snapshot_context(context: dict[str, Any]) -> bool`
- Produces: `_snapshot_guidance_answer() -> str`

- [ ] **Step 1: Add failing test for no-snapshot guidance**

```python
def test_autonomous_position_recommendation_requires_snapshot(db):
    class ExplodingPositionAgent:
        def run(self, **kwargs):
            raise AssertionError("position recommendation should not run without snapshot")

    service = AutonomousChatAgentService(session=db)
    service.position_agent = ExplodingPositionAgent()

    result = service.run(
        query="帮我推荐几个公务员岗位",
        user_id=existing_user_id,
        session_id=existing_session_id,
        position_profile={"major": "法学", "education": "本科"},
    )

    assert result["intent"] == "position_snapshot_required"
    assert "固定快照" in result["answer"]
    assert result["recommendations"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/gwy/test_autonomous_position_snapshot_gate.py::test_autonomous_position_recommendation_requires_snapshot -v`

Expected: FAIL because current chat path may still call autonomous tools.

- [ ] **Step 3: Implement gate before runtime**

Add helper:

```python
    def _looks_like_position_recommendation(self, query: str) -> bool:
        keywords = ("岗位推荐", "推荐岗位", "报考岗位", "适合什么岗位", "岗位分析", "职位推荐")
        return any(keyword in query for keyword in keywords)

    def _has_snapshot_context(self, context: dict[str, Any]) -> bool:
        snapshot = context.get("snapshot")
        task_id = context.get("position_analysis_task_id") or context.get("task_id")
        return bool(snapshot or task_id)

    def _snapshot_guidance_answer(self) -> str:
        return (
            "要做岗位推荐分析，请先在岗位表里筛选岗位并固定快照。"
            "固定快照后，我会基于这批岗位运行同一套 AgentRuntime，"
            "生成岗位分析计划、推荐报告、执行轨迹和复习计划。"
        )
```

In `run`, after building `context` and before constructing `AgentRuntime`:

```python
        if self._looks_like_position_recommendation(query) and not self._has_snapshot_context(context):
            answer = self._snapshot_guidance_answer()
            return {
                "answer": answer,
                "intent": "position_snapshot_required",
                "need_rag": False,
                "decision_branch": "position_snapshot_gate",
                "citations": [],
                "retrieval_trace": [{
                    "event": "SnapshotRequired",
                    "status": "done",
                    "step": "position_snapshot_gate",
                    "detail": "Position recommendation requires a fixed snapshot.",
                }],
                "rewritten_queries": [],
                "metadata_filter": None,
                "rerank_results": [],
                "recommendations": [],
                "risk_review": {},
                "report": answer,
                "study_plan": {},
                "need_more_info": False,
                "missing_fields": [],
                "recommendation_task_id": None,
                "historical_reference": False,
                "session_attachments": [],
            }
```

- [ ] **Step 4: Run chat gate test**

Run: `cd backend && pytest tests/gwy/test_autonomous_position_snapshot_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/autonomous_chat_agent_service.py backend/tests/gwy/test_autonomous_position_snapshot_gate.py
git commit -m "feat: require snapshots for chat position recommendations"
```

---

### Task 6: 验证持久化、飞书和回归测试

**Files:**
- Modify as needed: `backend/tests/api/routes/test_gwy_position_analysis_api.py`
- Modify as needed: `backend/tests/gwy/test_feishu_push_agent.py`

**Interfaces:**
- Consumes: existing `PositionAnalysisService._update_task_from_result`
- Consumes: existing `_push_report_to_feishu`

- [ ] **Step 1: Add persistence regression assertions**

Add or update a test so that after executing analysis:

```python
assert task.report_text
assert task.trace_json
assert task.output_json
assert "study_plan" in task.output_json or "runtime_state" in task.output_json
assert any(item.get("step") == "feishu_push" for item in task.trace_json)
```

- [ ] **Step 2: Run focused regression tests**

Run:

```bash
cd backend
pytest tests/gwy/test_position_snapshot_runtime_service.py tests/gwy/test_position_analysis_runtime_integration.py tests/gwy/test_autonomous_position_snapshot_gate.py tests/api/routes/test_gwy_position_analysis_api.py -v
```

Expected: PASS.

- [ ] **Step 3: Run backend lint or targeted full test if time allows**

Run: `cd backend && bash ./scripts/lint.sh`

Expected: no new lint errors from touched files.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/api/routes/test_gwy_position_analysis_api.py backend/tests/gwy/test_feishu_push_agent.py
git commit -m "test: cover snapshot runtime persistence"
```

---

## Self-Review Notes

- Spec coverage: runtime service, chat snapshot gate, position analysis runtime-first, fallback, persistence, Feishu trace, and tests are covered by Tasks 1-6.
- Placeholder scan: no `TBD`, `TODO`, or vague unimplemented task is intentionally left.
- Type consistency: the central interface is `PositionSnapshotRuntimeService.run(...) -> dict[str, Any]`, consumed by `PositionAnalysisService` and later chat integration.
