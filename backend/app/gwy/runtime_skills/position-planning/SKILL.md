---
name: position-planning
description: Plan civil-service position recommendation with PostgreSQL filtering, policy evidence, risk review, and study plan output.
---

# Position Planning

Use this skill when the user asks for岗位推荐、岗位匹配、报考建议、复习计划 or备考规划.

Required Agent Loop:

1. Call `todo_tasks` first and create 2-5 steps. Keep `todo_write` as a legacy-compatible alias only.
2. Call `load_snapshot`, then `analyze_snapshot_positions`; PostgreSQL is the source of truth for structured filtering.
3. Inspect returned `missing`, `confidence`, and `next_actions`. Do not compose a report while required evidence is missing.
4. Call `research_position_history` for recruitment and competition trends.
5. Call `retrieve_position_policy_evidence` for qualification, policy, and major-catalog evidence.
6. Call `verify_position_hidden_requirements` and `review_position_risks` for grassroots experience, professional tests, household registration, certificates, shifts, travel, and other restrictions.
7. Call `build_position_decision_matrix`; every position must receive one of `sprint`, `primary`, `backup`, `caution`, or `exclude`, with confidence, unknowns, verification tasks, and decision-change rules.
8. Call `generate_study_plan` when the user asks for a study plan or when preparation cost affects the decision.
9. Call `compose_snapshot_report` only after the decision matrix exists.
10. Call `validate_report_requirements`; if it returns `partial`, repair the report or gather missing evidence before final output.

Report requirements:

- Start with a direct selection conclusion, not a list of positions.
- Compare positions horizontally and explain why one is prioritized over another.
- Do not recommend every position.
- Never invent interview scores, ratios, probabilities, or announcement requirements.
- Turn every manual review item into a concrete material, field, official source, and action.

Never use RAG as a substitute for structured position filtering. Use RAG and web/MCP tools only to fill evidence gaps after PostgreSQL filtering.
