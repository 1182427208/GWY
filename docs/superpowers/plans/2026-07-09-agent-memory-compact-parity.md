# Agent Memory Compact Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring GwyPilot agent memory and context compaction into parity with `learn-claude-code` context compact behavior while persisting durable data to Redis/PostgreSQL.

**Architecture:** Add a focused compact module that mirrors the reference three-layer pipeline. Inject persistence and summarization dependencies into `AgentRuntime` so tests can use real code with small fakes.

**Tech Stack:** Python, FastAPI backend, SQLModel/PostgreSQL, Redis, Pytest.

## Global Constraints

- Keep backend code under `backend/app/gwy/`.
- Preserve the full-stack FastAPI template structure.
- Use PostgreSQL for durable long-term memory and compact transcript fallback.
- Use Redis as cache/short-term storage when available.
- Do not add frontend pages.
- Use TDD: write failing tests before production code changes.

---

### Task 1: Compact Core

**Files:**
- Modify: `backend/app/gwy/agent_runtime/compact.py`
- Test: `backend/tests/gwy/test_agent_runtime_compact.py`

**Interfaces:**
- Produces: `estimate_tokens(messages) -> int`
- Produces: `micro_compact(messages, keep_recent=3, preserve_result_tools=None) -> tuple[list[dict], dict | None]`
- Produces: `auto_compact(messages, summarizer, transcript_store, focus="", conversation_id=None) -> tuple[list[dict], dict]`

- [ ] Write failing tests for token estimation, micro compact, and auto compact.
- [ ] Run the tests and confirm they fail because functions/behavior are missing.
- [ ] Implement the compact functions with reference-compatible behavior.
- [ ] Run the compact tests and confirm they pass.

### Task 2: Transcript Persistence

**Files:**
- Modify: `backend/app/gwy/services/agent_memory_service.py`
- Test: `backend/tests/gwy/test_agent_memory_service.py`

**Interfaces:**
- Produces: `AgentMemoryService.save_compact_transcript(messages, focus="") -> dict[str, Any]`
- Produces: `AgentMemoryService.save_compact_summary(summary, transcript_id, focus="") -> None`

- [ ] Write failing tests for PostgreSQL fallback transcript persistence.
- [ ] Run the tests and confirm they fail because the new methods are missing.
- [ ] Implement transcript and summary persistence.
- [ ] Run the memory tests and confirm they pass.

### Task 3: Runtime Manual Compact Tool

**Files:**
- Modify: `backend/app/gwy/agent_runtime/builtin_tools.py`
- Modify: `backend/app/gwy/agent_runtime/loop.py`
- Test: `backend/tests/gwy/test_agent_runtime_compact.py`

**Interfaces:**
- Produces: built-in `compact` tool with optional `focus`.
- Consumes: compact core functions from Task 1.

- [ ] Write a failing runtime test where the model calls `compact`.
- [ ] Run the test and confirm manual compaction is not handled yet.
- [ ] Register `compact` and make `AgentRuntime` trigger summary compaction after the tool call.
- [ ] Run the runtime compact tests and confirm they pass.

### Task 4: Runtime Memory Services

**Files:**
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
- Modify: `backend/app/gwy/agent_runtime/loop.py`
- Test: `backend/tests/gwy/test_agent_runtime_compact.py`

**Interfaces:**
- Consumes: `AgentMemoryService` compact transcript APIs.
- Produces: `AgentRuntime(..., memory_service=None)`.

- [ ] Write a failing test proving auto compact saves transcript via memory service.
- [ ] Run the test and confirm the runtime does not persist compact transcripts yet.
- [ ] Pass memory service into `AgentRuntime` from autonomous chat service.
- [ ] Run focused runtime tests and confirm they pass.

### Task 5: Encoding Cleanup and Verification

**Files:**
- Modify touched corrupted strings in runtime/memory files only.

- [ ] Replace corrupted Chinese strings touched by this work with valid UTF-8 text.
- [ ] Run `python -m compileall` for modified backend modules.
- [ ] Run focused pytest files.

