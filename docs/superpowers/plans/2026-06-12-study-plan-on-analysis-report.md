# Study Plan on Analysis Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically generate a study plan after position analysis completes and render it inside the existing analysis report page.

**Architecture:** Position analysis already returns `recommendation_task_id` and produces structured recommendations. We will extend the analysis task payload to include a persisted `study_plan` object generated from the same recommendation set, then render that object as a dedicated section in the existing `/gwy/analysis` report page. The plan stays embedded in the report flow, so we preserve the current page structure while making the analysis-to-action handoff visible.

**Tech Stack:** FastAPI, SQLModel, Pydantic, React, TypeScript, Vite, Playwright, Pytest.

---

### Task 1: Add study plan generation to analysis task results

**Files:**
- Modify: `backend/app/gwy/services/position_analysis_service.py`
- Modify: `backend/app/gwy/agents/position_analysis_agent.py` if needed to expose stable recommendation fields for the study plan input
- Modify: `backend/app/api/routes/gwy_analysis.py` if response serialization needs to expose the new field
- Test: `backend/tests/api/routes/test_gwy_position_analysis_api.py`
- Test: `backend/tests/gwy/test_study_plan.py`

- [ ] **Step 1: Write the failing test**

```python
def test_position_analysis_task_api_returns_study_plan(client, normal_user_token_headers):
    response = client.post(
        "/api/v1/gwy/analysis/tasks",
        json={"snapshot": _sample_snapshot_payload(), "title": "北京岗位筛选分析"},
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["output_json"]["study_plan"]["plan"]["title"]
    assert payload["task"]["output_json"]["study_plan"]["markdown"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest backend/tests/api/routes/test_gwy_position_analysis_api.py -v`
Expected: FAIL because `study_plan` is not yet attached to the analysis task output.

- [ ] **Step 3: Write minimal implementation**

```python
study_plan_result = self._build_study_plan_result(result=result, user_profile=user_profile, recommendations=recommendations, task_id=task_row.id, user_id=user_uuid)
result["output_json"] = {**dict(result.get("output_json") or {}), "study_plan": study_plan_result}
```

and a helper that calls `StudyPlanService.generate(...)` with the current recommendation set, then stores the returned plan object into the analysis result payload.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest backend/tests/api/routes/test_gwy_position_analysis_api.py -v`
Expected: PASS, and the response payload contains a `study_plan` object.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/position_analysis_service.py backend/app/api/routes/gwy_analysis.py backend/tests/api/routes/test_gwy_position_analysis_api.py backend/tests/gwy/test_study_plan.py
git commit -m "feat: attach study plan to analysis results"
```

### Task 2: Render the study plan inside the analysis report page

**Files:**
- Modify: `frontend/src/routes/_layout/gwy/analysis.tsx`
- Modify: `frontend/src/client/types.gen.ts` if the generated client types need the new nested response shape
- Test: `frontend/tests/gwy-analysis.spec.ts`

- [ ] **Step 1: Write the failing test**

```typescript
test("analysis page renders the study plan section", async ({ page }) => {
  await page.route("**/api/v1/gwy/analysis/tasks/task-1", async (route) => {
    await route.fulfill({
      json: {
        id: "task-1",
        snapshot_id: "snapshot-1",
        user_id: "user-1",
        status: "completed",
        stage: "persist_result",
        input_json: {},
        output_json: {
          study_plan: {
            plan: { id: "plan-1", title: "2026 年复习规划", exam_type: "national", exam_year: 2026, total_weeks: 12, status: "completed" },
            phases: [{ id: "phase-1", phase_name: "基础阶段", phase_goal: "夯实基础", week_start: 1, week_end: 4, focus_subjects: ["行测"], study_hours_per_day: 4 }],
            subjects: [{ id: "subject-1", subject_name: "行测", subject_category: "笔试", weight_percent: 50, total_hours: 120, checklist_items: ["完成基础模块"], resources: ["题库"] }],
            tasks: [{ id: "task-item-1", week_number: 1, day_of_week: 1, subject: "行测", task_title: "基础练习", estimated_minutes: 60, priority: 1, completed: false }],
            markdown: "# 2026 年复习规划\n\n## 基础阶段",
          },
        },
        report_text: "# 宪位分析报告",
        trace_json: [],
        started_at: "2026-05-29T00:00:00Z",
        finished_at: "2026-05-29T00:00:01Z",
        created_at: "2026-05-29T00:00:00Z",
      },
    })
  })

  await page.goto("/gwy/analysis?task_id=task-1")

  await expect(page.getByText("复习规划")).toBeVisible()
  await expect(page.getByText("2026 年复习规划")).toBeVisible()
  await expect(page.getByText("基础阶段")).toBeVisible()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run --filter frontend test -- gwy-analysis.spec.ts`
Expected: FAIL because the page does not yet read or render `task.output_json.study_plan`.

- [ ] **Step 3: Write minimal implementation**

Add a `StudyPlanSummary` type and parse `taskOutput.study_plan` into a normalized object, then render a new report card near the analysis report preview with plan title, exam metadata, phase list, subject highlights, and a collapsible markdown preview.

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run --filter frontend test -- gwy-analysis.spec.ts`
Expected: PASS, and the study plan section is visible on the report page.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout/gwy/analysis.tsx frontend/tests/gwy-analysis.spec.ts frontend/src/client/types.gen.ts
git commit -m "feat: show study plan in analysis report"
```

### Task 3: Verify the end-to-end report flow

**Files:**
- Review: `backend/app/api/routes/gwy_analysis.py`
- Review: `backend/app/gwy/services/study_plan_service.py`
- Review: `frontend/src/routes/_layout/gwy/analysis.tsx`
- Review: `frontend/tests/gwy-analysis.spec.ts`
- Review: `backend/tests/api/routes/test_gwy_position_analysis_api.py`

- [ ] **Step 1: Run backend tests**

Run: `cd backend && bash ./scripts/test.sh`
Expected: all backend tests pass, including the new analysis/study plan coverage.

- [ ] **Step 2: Run frontend test**

Run: `bun run --filter frontend test -- gwy-analysis.spec.ts`
Expected: the report page test passes with the new study plan section.

- [ ] **Step 3: Run lint if code changed substantially**

Run: `cd backend && bash ./scripts/lint.sh`
Run: `bun run --filter frontend lint`
Expected: no new lint errors from the feature work.

- [ ] **Step 4: Commit the final state**

```bash
git add backend frontend
git commit -m "feat: auto-generate and display study plan after analysis"
```
