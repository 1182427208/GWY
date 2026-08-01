# Position Analysis Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Runtime-based position analysis loop from a filter/risk list into an evidence-aware position decision workflow with actionable reports.

**Architecture:** Keep `PositionSnapshotRuntimeService` and `AgentRuntime` as the top-level loop. Add narrow tools that write structured coverage and decision state into `ToolContext.state`; keep existing LangGraph-based specialist agents behind those tools. Make the report generator consume the decision matrix and pass through a deterministic report validator before final output.

**Tech Stack:** FastAPI, Python, SQLModel, LangGraph, AgentRuntime, Pytest.

## Global Constraints

- Keep the full-stack FastAPI template skeleton unchanged.
- Put new backend code under `backend/app/gwy/` where possible.
- PostgreSQL remains the source of truth for structured position filtering.
- Milvus/RAG only supplies policy and qualification evidence.
- Do not add frontend pages.
- Preserve existing dirty worktree changes and do not revert unrelated files.

---

### Task 1: Lock the Runtime contract with failing tests

**Files:**
- Create: `backend/tests/gwy/test_position_analysis_runtime_tools.py`
- Modify: `backend/app/gwy/runtime_skills/position-planning/SKILL.md`

**Interfaces:**
- Tests will require tool results to expose `status`, `covered`, `missing`, `confidence`, `next_actions`, and `data`.
- The skill will name the registered tools `analyze_snapshot_positions`, `research_position_history`, `retrieve_position_policy_evidence`, `verify_position_hidden_requirements`, `review_position_risks`, `build_position_decision_matrix`, `validate_report_requirements`, and `compose_snapshot_report`.

- [ ] Write tests asserting the skill names actual tools and that a position analysis result includes explicit missing-data guidance.
- [ ] Run `pytest backend/tests/gwy/test_position_analysis_runtime_tools.py -q` and confirm it fails because the new tools/contract do not exist.
- [ ] Update the skill instructions and test only the documented contract.
- [ ] Run the focused test and confirm it passes.

### Task 2: Add structured research and decision tools

**Files:**
- Create: `backend/app/gwy/services/position_decision_matrix_service.py`
- Modify: `backend/app/gwy/services/position_snapshot_runtime_service.py`
- Modify: `backend/app/gwy/agents/risk_review_agent.py`
- Test: `backend/tests/gwy/test_position_decision_matrix_service.py`
- Test: `backend/tests/gwy/test_risk_review_agent.py`

**Interfaces:**
- `PositionDecisionMatrixService.build(recommendations, research, risk_review, profile) -> dict[str, Any]` returns `items`, `tier_summary`, `missing`, `confidence`, and `next_actions`.
- Runtime tools write `position_research`, `policy_evidence`, `hidden_requirement_review`, `decision_matrix`, and `report_validation` into `ToolContext.state`.

- [ ] Write failing tests for hard-condition exclusion, medium-confidence primary/backup tiers, missing competition data, and deduplicated risk tasks.
- [ ] Run those tests and verify expected failures.
- [ ] Implement deterministic tiering and preparation-cost heuristics without fabricating numeric competition data.
- [ ] Add Runtime tools that invoke existing catalog, policy, web, risk, and specialist services and normalize outputs to the shared contract.
- [ ] Make risk review aggregate by `(position_id, risk_type)` and include verification tasks and decision-change rules.
- [ ] Run focused tests and confirm they pass.

### Task 3: Make the Agent Loop evidence-aware

**Files:**
- Modify: `backend/app/gwy/services/position_snapshot_runtime_service.py`
- Modify: `backend/app/gwy/services/position_analysis_service.py`
- Test: `backend/tests/gwy/test_position_snapshot_runtime_service.py`

**Interfaces:**
- Runtime state will contain `analysis_requirements`, `evidence_inventory`, `decision_matrix`, and `report_validation`.
- The system prompt will require planning, gap-driven tool calls, decision-matrix construction, validation, and only then report composition.

- [ ] Add failing tests proving report composition receives decision matrix and evidence coverage rather than only recommendations/risk review.
- [ ] Run the focused tests and confirm the old call shape fails.
- [ ] Add the state-aware tools and update the system prompt with bounded-loop completion rules.
- [ ] Preserve the existing Runtime fallback behavior while ensuring the normal path uses the enriched state.
- [ ] Run the focused tests and confirm they pass.

### Task 4: Replace list-style report generation with decision reporting

**Files:**
- Modify: `backend/app/gwy/agents/report_generator_agent.py`
- Create: `backend/app/gwy/services/report_quality_service.py`
- Test: `backend/tests/gwy/test_report_generator_agent.py`
- Test: `backend/tests/gwy/test_report_quality_service.py`

**Interfaces:**
- `ReportGeneratorAgent.run(..., decision_matrix=None, evidence_inventory=None, verification_tasks=None)` remains backward-compatible for existing callers.
- `ReportQualityService.validate(report, decision_matrix, risk_review) -> dict[str, Any]` returns `passed`, `missing_requirements`, `duplicate_risks`, and `next_actions`.

- [ ] Write failing tests requiring tiers, comparisons, per-position actions, and explicit unknowns in generated reports.
- [ ] Run focused tests and verify failure.
- [ ] Replace the report system/user prompt with the approved decision-reporting prompt and include structured decision input.
- [ ] Add deterministic quality validation and make Runtime retry/repair once before accepting an invalid report.
- [ ] Run focused tests and confirm they pass.

### Task 5: Full verification and diff review

**Files:**
- Review all files changed by Tasks 1-4.

- [ ] Run the focused backend tests for all changed services and agents.
- [ ] Run `cd backend && bash ./scripts/test.sh`.
- [ ] Run `cd backend && bash ./scripts/lint.sh`.
- [ ] Inspect `git diff --check` and `git status --short`.
- [ ] Confirm no frontend page or template skeleton was changed by this feature.
