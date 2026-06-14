# GwyPilot 岗位分析图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent position-analysis graph that turns an Excel-style saved snapshot into a persisted report, trace, and evidence-backed recommendation.

**Architecture:** The analysis flow will stay separate from chat. `Skills` will normalize snapshots and format deterministic outputs, a dedicated `position_analysis_graph` will orchestrate the workflow, and `Agentic RAG` will fetch evidence from PostgreSQL and Milvus without replacing rule-based filtering. The first version should run synchronously but still persist task and step rows so we can add async execution later without changing the API surface.

**Tech Stack:** FastAPI, SQLModel, Alembic, PostgreSQL, LangGraph, Milvus, Redis, React, TanStack Router, Playwright, OpenAPI-generated frontend client.

---

### Task 1: Add analysis persistence models and migration

**Files:**
- Modify: `backend/app/gwy/models.py`
- Modify: `backend/app/models.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/app/alembic/versions/a1b2c3d4e5f6_add_gwy_position_analysis_tables.py`
- Test: `backend/tests/gwy/test_position_analysis_models.py`

- [ ] **Step 1: Write the failing test**

```python
from sqlmodel import SQLModel

from app.gwy.models import (
    GwyPositionAnalysisSnapshot,
    GwyPositionAnalysisStep,
    GwyPositionAnalysisTask,
)


def test_position_analysis_models_are_registered():
    assert GwyPositionAnalysisSnapshot.__tablename__ == "gwy_position_analysis_snapshot"
    assert GwyPositionAnalysisTask.__tablename__ == "gwy_position_analysis_task"
    assert GwyPositionAnalysisStep.__tablename__ == "gwy_position_analysis_step"
    assert "gwy_position_analysis_snapshot" in SQLModel.metadata.tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_position_analysis_models.py -v`

Expected: fail with `ImportError` or `AttributeError` because the new analysis models do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Add three new SQLModel tables in `backend/app/gwy/models.py`:

```python
class GwyPositionAnalysisSnapshot(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_position_analysis_snapshot"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    title: str = Field(default="岗位分析快照", max_length=255, index=True)
    source_sheet: str | None = Field(default=None, max_length=255, index=True)
    filters_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    selected_position_ids: list[str] = Field(default_factory=list, sa_type=JSON)
    visible_columns: list[str] = Field(default_factory=list, sa_type=JSON)
    notes: str | None = Field(default=None)


class GwyPositionAnalysisTask(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_position_analysis_task"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    snapshot_id: uuid.UUID = Field(
        foreign_key="gwy_position_analysis_snapshot.id",
        index=True,
    )
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    status: str = Field(default="pending", max_length=32, index=True)
    stage: str = Field(default="created", max_length=64, index=True)
    input_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    output_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    report_text: str | None = Field(default=None)
    trace_json: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    error_message: str | None = Field(default=None)
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class GwyPositionAnalysisStep(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_position_analysis_step"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="gwy_position_analysis_task.id",
        index=True,
    )
    step_name: str = Field(max_length=128, index=True)
    status: str = Field(default="running", max_length=32, index=True)
    input_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    output_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    evidence_json: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    error_message: str | None = Field(default=None)
    started_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
```

Also import the three classes in `backend/app/models.py` and register them in `backend/tests/conftest.py` so the SQLite test schema picks them up. Create the Alembic revision with matching tables and indexes on `user_id`, `snapshot_id`, `task_id`, `status`, and `stage`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_position_analysis_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/models.py backend/app/models.py backend/tests/conftest.py backend/app/alembic/versions/a1b2c3d4e5f6_add_gwy_position_analysis_tables.py backend/tests/gwy/test_position_analysis_models.py
git commit -m "feat: add position analysis persistence models"
```

### Task 2: Build the analysis skills and dedicated graph

**Files:**
- Create: `backend/app/gwy/skills/position_analysis_skills.py`
- Create: `backend/app/gwy/prompts/position_analysis.py`
- Create: `backend/app/gwy/agents/position_analysis_agent.py`
- Create: `backend/app/gwy/services/position_analysis_service.py`
- Test: `backend/tests/gwy/test_position_analysis_agent.py`

- [ ] **Step 1: Write the failing test**

```python
def test_position_analysis_graph_returns_trace_and_report(db, monkeypatch):
    agent = PositionAnalysisAgent(
        session=db,
        chat_service=FakeChatService(),
        catalog_service=FakePositionCatalogService(),
        policy_rag_service=FakePolicyRagService(),
        risk_review_agent=FakeRiskReviewAgent(),
        report_generator_agent=FakeReportGeneratorAgent(),
    )

    result = agent.run(snapshot=sample_snapshot(), user_id=user_id)

    assert result["status"] == "completed"
    assert [item["step"] for item in result["trace"][:3]] == [
        "load_snapshot",
        "normalize_snapshot",
        "build_analysis_scope",
    ]
    assert result["report"].startswith("#")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_position_analysis_agent.py -v`

Expected: fail with `ModuleNotFoundError` because the new analysis agent and skill modules do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `backend/app/gwy/skills/position_analysis_skills.py` with pure helpers for:

- `normalize_analysis_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]`
- `build_analysis_scope(snapshot: dict[str, Any]) -> dict[str, Any]`
- `render_analysis_outline(scope: dict[str, Any], evidence: list[dict[str, Any]]) -> list[str]`
- `cleanup_analysis_report(text: str) -> str`

Create `backend/app/gwy/agents/position_analysis_agent.py` as a dedicated LangGraph pipeline with nodes:

1. `load_snapshot`
2. `normalize_snapshot`
3. `build_analysis_scope`
4. `retrieve_position_facts`
5. `retrieve_policy_evidence`
6. `risk_review`
7. `compose_report`
8. `refine_report`
9. `persist_result`

The agent should reuse existing components instead of rewriting them:

- `PositionCatalogService` for structured岗位事实和候选岗位分析
- `PolicyRagService` or `MilvusPolicyStore` for政策证据检索
- `RiskReviewAgent` for风险复核
- `ReportGeneratorAgent` for报告结构化输出

Create `backend/app/gwy/services/position_analysis_service.py` as the orchestration layer that:

- creates a `GwyPositionAnalysisSnapshot`
- creates a `GwyPositionAnalysisTask`
- invokes `PositionAnalysisAgent`
- persists trace, report, and final status back to the task row

Create `backend/app/gwy/prompts/position_analysis.py` with a dedicated prompt that tells the report generator to stay in the “岗位决策顾问” role, keep language direct, and format results as summary, evidence, risks, and next steps.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_position_analysis_agent.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/skills/position_analysis_skills.py backend/app/gwy/prompts/position_analysis.py backend/app/gwy/agents/position_analysis_agent.py backend/app/gwy/services/position_analysis_service.py backend/tests/gwy/test_position_analysis_agent.py
git commit -m "feat: add position analysis graph"
```

### Task 3: Expose analysis APIs and regenerate the frontend client

**Files:**
- Create: `backend/app/api/routes/gwy_analysis.py`
- Modify: `backend/app/api/main.py`
- Test: `backend/tests/api/routes/test_gwy_position_analysis_api.py`
- Create: `frontend/openapi.json`
- Modify: `frontend/src/client/index.ts`
- Modify: `frontend/src/client/sdk.gen.ts`
- Modify: `frontend/src/client/schemas.gen.ts`
- Modify: `frontend/src/client/types.gen.ts`

- [ ] **Step 1: Write the failing test**

```python
def test_position_analysis_task_api_returns_report(client, normal_user_token_headers, db):
    response = client.post(
        "/api/v1/gwy/analysis/tasks",
        json={
            "snapshot": sample_snapshot_payload(),
            "title": "北京市岗位筛选分析",
        },
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["task"]["stage"] == "persist_result"
    assert payload["trace"][0]["step"] == "load_snapshot"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/api/routes/test_gwy_position_analysis_api.py -v`

Expected: fail with `404 Not Found` or import errors because the new analysis route does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Add a new `gwy_analysis.router` with these endpoints:

- `POST /api/v1/gwy/analysis/tasks`
- `GET /api/v1/gwy/analysis/tasks/{task_id}`
- `GET /api/v1/gwy/analysis/tasks/{task_id}/trace`
- `GET /api/v1/gwy/analysis/tasks/{task_id}/report`
- `GET /api/v1/gwy/analysis/snapshots/{snapshot_id}`

Keep the first version synchronous: the task should be created, executed, and persisted in one request, but the API must still return the task id, status, report text, and structured trace so the frontend can render it without guessing.

Update `backend/app/api/main.py` to include the new router alongside the existing `gwy` router.

After the backend routes are added, export the new schema from `http://localhost:8000/api/v1/openapi.json`, save it as `frontend/openapi.json`, and run:

```bash
cd frontend
bun run generate-client
```

That will refresh the generated client files under `frontend/src/client/` for the new analysis endpoints.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/api/routes/test_gwy_position_analysis_api.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/gwy_analysis.py backend/app/api/main.py backend/tests/api/routes/test_gwy_position_analysis_api.py frontend/openapi.json frontend/src/client/index.ts frontend/src/client/sdk.gen.ts frontend/src/client/schemas.gen.ts frontend/src/client/types.gen.ts
git commit -m "feat: expose position analysis api"
```

### Task 4: Build the dedicated analysis page and connect the Excel-style filter page

**Files:**
- Create: `frontend/src/routes/_layout/gwy/analysis.tsx`
- Modify: `frontend/src/components/GwyPositionsExcelPage.tsx`
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx`
- Modify: `frontend/src/routeTree.gen.ts`
- Test: `frontend/tests/gwy-analysis.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { expect, test } from "@playwright/test"

test("analysis page renders the report shell", async ({ page }) => {
  await page.route("**/api/v1/gwy/analysis/tasks/*", async (route) => {
    await route.fulfill({
      json: {
        task: { id: "task-1", status: "completed", stage: "persist_result" },
        report: "# 岗位分析报告",
        trace: [{ step: "load_snapshot", status: "done" }],
      },
    })
  })

  await page.goto("/gwy/analysis?task_id=task-1")
  await expect(page.getByRole("heading", { name: "岗位分析报告" })).toBeVisible()
  await expect(page.getByText("load_snapshot")).toBeVisible()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && bun run test -- --grep "analysis page renders the report shell"`

Expected: fail because the new route does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `frontend/src/routes/_layout/gwy/analysis.tsx` as a dedicated fixed-height page with three panels:

- left: saved snapshots and task history
- center: report body
- right: step trace and evidence references

The page should use a scrolling container with a fixed viewport height, so long reports do not stretch the whole layout.

Update `frontend/src/components/GwyPositionsExcelPage.tsx` so the current inline analysis panel is replaced by a simple action flow:

1. save the current grid snapshot
2. submit the snapshot to the analysis task API
3. navigate to `/gwy/analysis?task_id=...`

That keeps the Excel-style filtering page focused and moves the report experience into its own surface.

Add a sidebar entry in `frontend/src/components/Sidebar/AppSidebar.tsx` so users can open the analysis page directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && bun run test -- --grep "analysis page renders the report shell"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout/gwy/analysis.tsx frontend/src/components/GwyPositionsExcelPage.tsx frontend/src/components/Sidebar/AppSidebar.tsx frontend/src/routeTree.gen.ts frontend/tests/gwy-analysis.spec.ts
git commit -m "feat: add position analysis report page"
```

## Self-Review Checklist

Before coding, verify the plan covers every requirement from `docs/superpowers/specs/2026-05-29-gwy-analysis-graph-design.md`:

- Snapshot persistence is covered by Task 1.
- Independent analysis graph orchestration is covered by Task 2.
- PostgreSQL and Milvus evidence flow is covered by Task 2.
- API access and client regeneration are covered by Task 3.
- Separate analysis UI and fixed-height layout are covered by Task 4.
- Testing exists for models, graph behavior, API, and frontend shell.

No placeholders remain in this plan.
