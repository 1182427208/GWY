import { expect, test } from "@playwright/test"

test("gwy positions cache survives route switches", async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.clear()
  })

  let gridRequests = 0

  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({
      json: {
        id: "user-1",
        email: "tester@example.com",
        full_name: "Test User",
      },
    })
  })

  await page.route("**/api/v1/gwy/positions/page-state", async (route) => {
    await route.fulfill({
      json: {
        activeSheet: "中央党群机关",
        sheets: {},
        savedSnapshots: {},
      },
    })
  })

  await page.route("**/api/v1/gwy/positions/grid", async (route) => {
    gridRequests += 1
    expect(route.request().url()).toContain("year=2026")
    await route.fulfill({
      json: {
        data: [
          {
            id: "pos-1",
            department_code: "001",
            department_name: "中央办公厅",
            office_name: "办公厅",
            job_title: "岗位A",
            position_attribute: "普通职位",
            position_distribution: "北京",
            position_desc: "测试岗位",
            position_code: "P-1",
            institution_level: "中央",
            exam_category: "国考",
            recruit_count: 1,
            major_requirement: "不限",
            education_requirement: "本科",
            degree_requirement: "学士",
            political_status_requirement: "不限",
            grassroots_years_requirement: "不限",
            grassroots_project_experience: "不限",
            professional_test_in_interview: "否",
            interview_ratio: "3:1",
            work_location: "北京",
            household_registration_location: "北京",
            remarks: "",
            department_website: "",
            contact_phone_1: "",
            contact_phone_2: "",
            contact_phone_3: "",
            source_file: "2026岗位表.xlsx",
            source_sheet: "中央党群机关",
            source_row_number: 1,
            raw_data: {},
          },
        ],
        count: 1,
        page: 1,
        page_size: 1,
        filters: {},
      },
    })
  })

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
          policy_evidence: [],
          report_outline: ["概览"],
        },
        report_text: "# 岗位分析报告\n\n## 概览\n- 示例内容",
        trace_json: [],
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
          title: "中央党群机关岗位分析快照",
          source_sheet: "中央党群机关",
          filters_json: {},
          snapshot_json: {},
          selected_position_ids: ["pos-1"],
          visible_columns: ["department_name", "job_title"],
          notes: "",
          created_at: "2026-05-29T00:00:00Z",
        },
      })
    },
  )

  await page.goto("/gwy/positions")
  await expect(page.getByText("中央办公厅")).toBeVisible()
  expect(gridRequests).toBe(1)

  await page.goto("/gwy/analysis?task_id=task-1")
  await expect(
    page.getByRole("heading", { name: "宀椾綅鍒嗘瀽鎶ュ憡" }),
  ).toBeVisible()

  await page.goto("/gwy/positions")
  await expect(page.getByText("中央办公厅")).toBeVisible()
  expect(gridRequests).toBe(1)
})
