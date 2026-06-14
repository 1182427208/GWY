# GwyPilot 岗位推荐页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立的 `/gwy/positions` 岗位推荐页面，支持 PostgreSQL 职位表的 Excel 风格筛选、分页展示、岗位勾选和分析。

**Architecture:** 前端新增独立页面与左侧菜单入口，页面通过轻量接口拉取 PostgreSQL 职位数据并做服务端筛选分页。后端新增岗位列表接口和岗位分析接口，列表负责精确筛选与分页，分析复用现有岗位推荐 agent 输出匹配解释与风险提示，避免把推荐逻辑塞进对话页。

**Tech Stack:** FastAPI, SQLModel, PostgreSQL, React, TypeScript, TanStack Router, TanStack Query, existing Gwy position recommendation agent.

---

### Task 1: Add backend position list API

**Files:**
- Modify: `backend/app/api/routes/gwy.py`
- Modify: `backend/app/gwy/skills/position_recommendation_skills.py`
- Test: `backend/tests/api/routes/test_gwy_positions_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_positions_list_filters_and_pages(db: Session) -> None:
    response = client.get(
        "/api/v1/gwy/positions",
        params={"major": "工学", "education": "硕士研究生", "page": 1, "page_size": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert payload["data"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/routes/test_gwy_positions_api.py -q`
Expected: fail because `/api/v1/gwy/positions` is not implemented yet.

- [ ] **Step 3: Write minimal implementation**

```python
@router.get("/positions", response_model=PositionListResponse)
def list_positions(
    session: SessionDep,
    major: str | None = None,
    education: str | None = None,
    degree: str | None = None,
    political_status: str | None = None,
    region: str | None = None,
    department: str | None = None,
    job_title: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PositionListResponse:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/routes/test_gwy_positions_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/gwy.py backend/app/gwy/skills/position_recommendation_skills.py backend/tests/api/routes/test_gwy_positions_api.py
git commit -m "feat: add gwy positions list api"
```

### Task 2: Add backend analysis API for selected positions

**Files:**
- Modify: `backend/app/api/routes/gwy.py`
- Modify: `backend/app/gwy/agents/position_decision_agent.py`
- Test: `backend/tests/api/routes/test_gwy_positions_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_positions_analyze_selected_items(db: Session) -> None:
    response = client.post(
        "/api/v1/gwy/positions/analyze",
        json={"position_ids": ["..."], "query": "我想在北京找工学硕士岗位"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "recommendations" in payload
    assert "analysis" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/routes/test_gwy_positions_api.py -q`
Expected: fail because `/api/v1/gwy/positions/analyze` is not implemented yet.

- [ ] **Step 3: Write minimal implementation**

```python
@router.post("/positions/analyze", response_model=PositionAnalyzeResponse)
def analyze_positions(payload: PositionAnalyzeRequest, session: SessionDep) -> PositionAnalyzeResponse:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/routes/test_gwy_positions_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/gwy.py backend/app/gwy/agents/position_decision_agent.py backend/tests/api/routes/test_gwy_positions_api.py
git commit -m "feat: add gwy position analysis api"
```

### Task 3: Create frontend positions page and sidebar entry

**Files:**
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx`
- Create: `frontend/src/routes/_layout/gwy/positions.tsx`
- Modify: `frontend/src/routes/_layout.tsx`
- Test: `frontend` build

- [ ] **Step 1: Write the failing UI route**

```tsx
export const Route = createFileRoute("/_layout/gwy/positions")({
  component: PositionsPage,
  head: () => ({ meta: [{ title: "岗位推荐 - GwyPilot" }] }),
})
```

- [ ] **Step 2: Run build to verify route is missing**

Run: `cd frontend && npm run build`
Expected: fail or route unresolved until the page exists.

- [ ] **Step 3: Write minimal implementation**

```tsx
const sidebarItems = [...baseItems, { icon: Briefcase, title: "岗位推荐", path: "/gwy/positions" }]
```

```tsx
<PositionsFilterPanel />
<PositionsTable />
<SelectedPositionsAnalysis />
```

- [ ] **Step 4: Run build to verify it passes**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Sidebar/AppSidebar.tsx frontend/src/routes/_layout.tsx frontend/src/routes/_layout/gwy/positions.tsx
git commit -m "feat: add gwy positions page"
```

### Task 4: Add table filters, pagination, and selected-position analysis UI

**Files:**
- Create: `frontend/src/routes/_layout/gwy/positions.tsx`
- Modify: `frontend/src/routes/_layout/gwy/chat.tsx` only if shared types/utilities need reuse
- Test: `frontend/src/routes/_layout/gwy/positions.tsx` manual build

- [ ] **Step 1: Define filter controls**
- [ ] **Step 2: Render server-side paginated table**
- [ ] **Step 3: Support row selection and selected list**
- [ ] **Step 4: Call analyze API for selected positions**
- [ ] **Step 5: Render recommendation cards and analysis text**

### Task 5: Add tests and docs

**Files:**
- Create: `backend/tests/api/routes/test_gwy_positions_api.py`
- Create: `frontend/src/routes/_layout/gwy/positions.tsx` if not already covered
- Create/Modify: `docs/GwyPilot_RAG_Implementation_Summary.md` if necessary

- [ ] **Step 1: Add backend API tests**
- [ ] **Step 2: Verify frontend build**
- [ ] **Step 3: Update docs with the new page and flow**

