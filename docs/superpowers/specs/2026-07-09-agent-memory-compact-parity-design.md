# Agent Memory and Context Compact Parity Design

## Goal

Implement short-term memory, long-term memory, and context compaction to match `learn-claude-code-main/agents/s06_context_compact.py`, with one storage adaptation: long-term memory and compact transcripts are persisted to Redis and PostgreSQL instead of local transcript files.

## Scope

- Preserve the existing FastAPI/full-stack template structure.
- Keep new backend logic under `backend/app/gwy/`.
- Do not add frontend pages.
- Do not use RAG as a substitute for structured position filtering.
- Fix corrupted Chinese runtime prompts or fallback strings touched by this work.

## Reference Behavior

Context compaction must use the same three-layer pipeline as `learn-claude-code`:

1. `micro_compact` runs before every model call.
2. If estimated tokens exceed `50000`, `auto_compact` saves the full transcript, asks the LLM for a continuity summary, and replaces all messages with the compressed summary.
3. A model-callable `compact` tool triggers the same summary compaction immediately, with an optional `focus` string.

The reference token estimator is `len(str(messages)) // 4`. Tool-result compaction keeps the latest three tool results and replaces older long non-preserved tool results with `[Previous: used {tool_name}]`. Read/reference tools are preserved.

## Storage Adaptation

The reference implementation writes full transcripts to `.transcripts/*.jsonl`. GwyPilot will instead store transcript payloads in `GwyConversationMemory` and Redis:

- PostgreSQL key: `compact_transcript:<id>`
- Redis key: `gwy:compact:transcript:<conversation_id>:<id>`
- Summary key: `compact_summary`

Redis is an optimization. PostgreSQL is the durable fallback.

## Runtime Integration

`AgentRuntime` will own the compaction lifecycle:

- Run `micro_compact` at the start of each turn.
- Run `auto_compact` when the token estimate crosses the threshold.
- Register and handle a `compact` tool result as a manual compaction request.
- Emit `Compact` trace events for micro, auto, and manual compaction.

The runtime will continue returning final answer, trace, state, and messages.

## Memory Integration

Short-term memory remains session-scoped and Redis-first with PostgreSQL fallback. Long-term memory remains PostgreSQL-first with Redis cache:

- `AgentMemoryService` handles working/session memory and compact transcript persistence.
- `LongTermMemoryService` handles profile enrichment, decisions, experiences, and cross-session summaries.
- Runtime memory tools should use the memory service when available, and fall back to runtime state only when no persistence context exists.

## Testing

Focused backend tests will cover:

- `micro_compact` preserves recent tool results and read/reference tool outputs.
- `auto_compact` saves transcript payloads through the repository interface and replaces messages with the LLM-generated continuity summary.
- `compact` tool triggers manual compaction in `AgentRuntime`.
- `AgentMemoryService` can persist and reload compact transcripts through PostgreSQL fallback.

