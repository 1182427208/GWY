import { expect, test } from "@playwright/test"

test("gwy evals page shows run, case, trace, and observation details", async ({
  page,
}) => {
  await page.route("**/api/v1/gwy/evals/runs", async (route) => {
    await route.fulfill({
      json: [
        {
          id: "run-1",
          source_type: "online",
          task_type: "policy_qa",
          status: "passed",
          query: "policy question",
          summary: {
            trace_complete: true,
            failure_reasons: [],
            scores: {
              task_success: { passed: true, metrics: { success: 1 } },
              rag: { passed: true, metrics: { recall_at_k: 1 } },
            },
          },
          created_at: "2026-08-01T08:00:00Z",
        },
      ],
    })
  })

  await page.route("**/api/v1/gwy/evals/datasets", async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.route(
    "**/api/v1/gwy/evals/datasets/import-defaults",
    async (route) => {
      await route.fulfill({ json: [] })
    },
  )

  await page.route("**/api/v1/gwy/evals/runs/run-1/cases", async (route) => {
    await route.fulfill({
      json: [
        {
          id: "case-result-1",
          case_id: "case-1",
          status: "passed",
          passed: true,
          scores: {
            task_success: {
              passed: true,
              metrics: { success: 1 },
              failure_reasons: [],
              details: {},
            },
            rag: {
              passed: true,
              metrics: {
                recall_at_k: 1,
                citation_support_rate: 1,
                answer_point_coverage: 1,
              },
              failure_reasons: [],
              details: {},
            },
          },
          observation: {
            final_answer: "answer",
            status: "success",
            citations: [{ doc_id: "doc-1" }],
            retrieved_documents: [{ doc_id: "doc-1" }],
            tool_calls: [{ tool: "search_policy_knowledge", success: true }],
            memory_before: {},
            memory_after: {},
            agent_steps: 3,
            latency_ms: 1200,
            trace: [
              { event: "LLMStart", status: "running", step: "agent_loop" },
              { event: "Stop", status: "done", step: "agent_loop" },
            ],
          },
          failure_reasons: [],
          trace: [
            { event: "LLMStart", status: "running", step: "agent_loop" },
            { event: "Stop", status: "done", step: "agent_loop" },
          ],
        },
      ],
    })
  })

  await page.goto("/gwy/evals")

  await expect(
    page.getByText("评测记录", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("评测报告", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: /policy question/ }).first(),
  ).toBeVisible()
  await expect(page.locator("body")).toContainText("case-1")
  await expect(page.locator("body")).toContainText("search_policy_knowledge")
  await expect(page.locator("body")).toContainText("final_answer")
})
