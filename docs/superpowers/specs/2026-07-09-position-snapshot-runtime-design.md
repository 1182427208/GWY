# Position Snapshot AgentRuntime Design

## Goal

Unify job recommendation and job analysis around a snapshot-first AgentRuntime flow.
When the user asks for job recommendation in chat without a fixed snapshot, the
system should guide them to filter the job table and pin a snapshot first. Once a
snapshot exists, both chat and the position analysis task should use the same
snapshot-driven AgentRuntime path to plan, inspect evidence, generate the report,
build a study plan, and optionally push the report to Feishu.

## Non-Goals

- Do not add new frontend pages.
- Do not replace structured PostgreSQL filtering with RAG.
- Do not remove the existing `PositionAnalysisAgent` immediately; keep it as a
  fallback while the runtime path is introduced.
- Do not change the full-stack template structure or app startup flow.

## Proposed Architecture

Add a snapshot-oriented runtime service, tentatively named
`PositionSnapshotRuntimeService`, under `backend/app/gwy/services/`.

This service will:

- Build an `AgentRuntime` with a system prompt specific to snapshot-based job
  analysis.
- Inject snapshot data, user profile, task id, year, exam type, and existing
  recommendation context into runtime state.
- Register tools that let the model inspect the snapshot and produce the final
  artifacts.
- Return a result shape compatible with `PositionAnalysisService`: `status`,
  `stage`, `report`, `trace`, `output_json`, `recommendations`,
  `risk_review`, `study_plan`, `needs_more_info`, and related metadata.

`PositionAnalysisService` should call this runtime service instead of directly
calling `PositionAnalysisAgent`. If the runtime fails because tool calling or the
LLM provider is unavailable, it should fall back to the existing
`PositionAnalysisAgent` path.

## Runtime Tools

The runtime should reuse the existing generic tools from
`register_builtin_tools`, especially `todo_write`, `load_skill`, context, and
memory tools.

Snapshot-specific tools should be registered by the new service:

- `load_snapshot`: load and summarize the fixed snapshot, including selected
  position ids, visible columns, filters, notes, and source sheet.
- `analyze_snapshot_positions`: use PostgreSQL-backed catalog analysis for the
  snapshot position ids and profile, preserving structured filtering as the
  source of job facts.
- `search_policy_evidence`: retrieve policy evidence through the existing policy
  evidence/RAG services where needed for eligibility, restrictions, and exam
  rules.
- `review_position_risks`: run the existing risk review agent against current
  recommendations.
- `generate_study_plan`: run the existing study plan agent and store the
  generated markdown in runtime state.
- `compose_snapshot_report`: let the model compose or refine a final Markdown
  report from the runtime state, snapshot facts, risk review, evidence, and
  study plan.

The prompt should require the model to call `todo_write` first for non-trivial
analysis, then decide which tools are needed. It should explicitly instruct that
the report must be grounded in PostgreSQL job facts and policy evidence, and that
unknown data must be marked as unknown instead of invented.

## Chat Integration

Chat job recommendation should become snapshot-first:

- If the user asks for job recommendation but the request has no fixed snapshot
  or task context, return a clear guidance response asking the user to filter the
  job table and pin a snapshot before analysis.
- If a snapshot or task context is available, call the same
  `PositionSnapshotRuntimeService` used by the position analysis task.

This removes the split where chat can produce one recommendation flow while the
analysis task produces another.

## Persistence And Trace

Keep current persistence behavior:

- `GwyPositionAnalysisTask.report_text` stores the final report.
- `GwyPositionAnalysisTask.trace_json` stores the runtime trace.
- `GwyPositionAnalysisStep` is populated from runtime trace events.
- Report markdown is archived under `data/gwy_analysis_reports/`.
- Study plan results remain persisted by `StudyPlanService` when generated from
  the analysis task.
- Feishu push remains owned by `PositionAnalysisService` after task completion.

The runtime trace should preserve AgentRuntime event names such as
`UserPromptSubmit`, `LLMStart`, `ToolUse`, `PostToolUse`, `Stop`, and tool step
names. A thin adapter can map these into the existing step persistence format.

## Error Handling

- If no snapshot exists in chat, do not run fallback recommendation; guide the
  user to create a snapshot.
- If runtime execution fails inside the position analysis task, record an error
  recovery trace entry and fall back to `PositionAnalysisAgent`.
- If a snapshot has insufficient user profile information, return
  `needs_more_info` with missing fields and clarifying questions instead of
  forcing a report.
- If Feishu webhook is not configured, keep the existing skipped push behavior.

## Testing

Add focused backend tests for:

- Chat recommendation without snapshot returns snapshot guidance and does not
  call PostgreSQL recommendation.
- Position analysis service invokes the snapshot runtime path when a snapshot
  task is executed.
- Runtime fallback uses the legacy `PositionAnalysisAgent` when runtime raises.
- Runtime output is persisted into task report, trace, output JSON, and report
  archive.
- Feishu push still appends its trace after successful or skipped analysis.

## Rollout

Introduce the runtime path behind the service boundary first. Keep legacy
`PositionAnalysisAgent` available as fallback until the new flow is stable and
covered by tests.
