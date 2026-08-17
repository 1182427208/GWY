import { expect, test } from "@playwright/test"

test("analysis page renders the report shell", async ({ page }) => {
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
          analysis_strategy: {
            strategy_name: "explore_then_verify",
            planning_strategy: "plan_and_solve",
            evidence_strategy: "react",
            decision_style: "explore_then_verify",
            research_budget: {
              selected_count: 1,
              web_search_enabled: true,
            },
            priority_sources: [
              "postgres_history",
              "milvus_policy",
              "web_search",
            ],
            summary_lines: [
              "strategy: explore_then_verify",
              "planning: plan_and_solve",
              "evidence: react",
              "history: no",
            ],
            research_targets: [
              {
                index: 1,
                position_id: "pos-1",
                department_name: "beijing bureau",
                office_name: "planning division",
                job_title: "general management",
                position_code: "BJ-001",
                history_priority: "low",
                needs_web_search: true,
                focus: ["hard_requirements", "history", "competition_trend"],
                history_summary: {
                  record_count: 0,
                },
              },
            ],
          },
          policy_evidence: [
            {
              id: "doc-1",
              doc_title: "job_notice",
              source_file: "notice.pdf",
              content: "sample evidence",
              score: 0.92,
            },
          ],
          agent_journey: [
            {
              step: "plan_analysis_strategy",
              status: "done",
              detail: "strategy plan generated",
              elapsed_ms: 14,
            },
            {
              step: "research_positions",
              status: "done",
              detail: "position research completed",
              elapsed_ms: 22,
            },
          ],
          report_outline: ["overview", "risk"],
        },
        report_text: "# Report\n\n## Overview\n- sample content",
        trace_json: [
          {
            step: "load_snapshot",
            status: "done",
            detail: "snapshot loaded",
            elapsed_ms: 12,
            evidence_refs: [
              {
                doc_title: "job_notice",
                source_file: "notice.pdf",
                content: "sample evidence",
                score: 0.92,
              },
            ],
          },
        ],
        error_message: null,
        started_at: "2026-05-29T00:00:00Z",
        finished_at: "2026-05-29T00:00:01Z",
        created_at: "2026-05-29T00:00:00Z",
      },
    })
  })

  await page.route(
    "**/api/v1/gwy/analysis/snapshots/snapshot-1",
    async (route) => {
      await route.fulfill({
        json: {
          id: "snapshot-1",
          user_id: "user-1",
          title: "\u5317\u4eac\u5c97\u4f4d\u5206\u6790\u5feb\u7167",
          source_sheet: "Sheet1",
          filters_json: { major: "computer science", region: "beijing" },
          snapshot_json: {},
          selected_position_ids: ["pos-1"],
          visible_columns: ["department_name", "job_title"],
          notes: "example note",
          created_at: "2026-05-29T00:00:00Z",
        },
      })
    },
  )

  await page.goto("/gwy/analysis?task_id=task-1")

  await expect(page.getByText("load_snapshot")).toBeVisible()
  await expect(
    page
      .getByText("\u5317\u4eac\u5c97\u4f4d\u5206\u6790\u5feb\u7167", {
        exact: true,
      })
      .first(),
  ).toBeVisible()
  await expect(page.getByText("Agent \u7b56\u7565\u5730\u56fe")).toBeVisible()
  await expect(
    page.getByText("explore_then_verify", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("plan_and_solve", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("research_positions", { exact: true }).first(),
  ).toBeVisible()
})

test("analysis page renders the study plan section", async ({ page }) => {
  await page.route("**/api/v1/gwy/analysis/tasks/task-2", async (route) => {
    await route.fulfill({
      json: {
        id: "task-2",
        snapshot_id: "snapshot-2",
        user_id: "user-1",
        status: "completed",
        stage: "persist_result",
        input_json: {},
        output_json: {
          study_plan: {
            status: "completed",
            plan: {
              id: "plan-1",
              title: "2026 \u5e74\u590d\u4e60\u89c4\u5212",
              exam_type: "national",
              exam_year: 2026,
              status: "completed",
              study_hours_per_day: 4,
              total_weeks: 12,
            },
            phases: [
              {
                id: "phase-1",
                phase_order: 1,
                phase_name: "\u57fa\u7840\u9636\u6bb5",
                phase_goal: "\u5937\u5b9e\u57fa\u7840",
                week_start: 1,
                week_end: 4,
                focus_subjects: ["\u884c\u6d4b"],
                study_hours_per_day: 4,
              },
            ],
            subjects: [
              {
                id: "subject-1",
                subject_name: "\u884c\u6d4b",
                subject_category: "\u7b14\u8bd5",
                weight_percent: 50,
                total_hours: 120,
                checklist_items: ["\u57fa\u7840\u7ec3\u4e60"],
                resources: ["\u9898\u5e93"],
              },
            ],
            tasks: [
              {
                id: "task-item-1",
                week_number: 1,
                day_of_week: 1,
                subject: "\u884c\u6d4b",
                task_title: "\u57fa\u7840\u7ec3\u4e60",
                task_description: "\u57fa\u7840\u7ec3\u4e60",
                estimated_minutes: 60,
                priority: 1,
                completed: false,
              },
            ],
            markdown:
              "# 2026 \u5e74\u590d\u4e60\u89c4\u5212\n\n## \u57fa\u7840\u9636\u6bb5\n- \u6253\u57fa\u7840",
          },
        },
        report_text: "# Report\n\n## Overview\n- sample content",
        trace_json: [
          {
            step: "load_snapshot",
            status: "done",
            detail: "snapshot loaded",
            elapsed_ms: 12,
            evidence_refs: [],
          },
        ],
        error_message: null,
        started_at: "2026-05-29T00:00:00Z",
        finished_at: "2026-05-29T00:00:01Z",
        created_at: "2026-05-29T00:00:00Z",
      },
    })
  })

  await page.route(
    "**/api/v1/gwy/analysis/snapshots/snapshot-2",
    async (route) => {
      await route.fulfill({
        json: {
          id: "snapshot-2",
          user_id: "user-1",
          title: "\u5317\u4eac\u5c97\u4f4d\u7b5b\u9009\u5feb\u7167",
          source_sheet: "Sheet1",
          filters_json: { major: "computer science", region: "beijing" },
          snapshot_json: {},
          selected_position_ids: ["pos-1"],
          visible_columns: ["department_name", "job_title"],
          notes: "example note",
          created_at: "2026-05-29T00:00:00Z",
        },
      })
    },
  )

  await page.goto("/gwy/analysis?task_id=task-2")

  await expect(
    page.getByText("\u590d\u4e60\u89c4\u5212", { exact: true }),
  ).toBeVisible()
  await expect(
    page
      .getByText("2026 \u5e74\u590d\u4e60\u89c4\u5212", { exact: true })
      .first(),
  ).toBeVisible()
  await expect(
    page.getByText("\u57fa\u7840\u9636\u6bb5", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("\u884c\u6d4b", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("\u57fa\u7840\u7ec3\u4e60", { exact: true }).first(),
  ).toBeVisible()
})
