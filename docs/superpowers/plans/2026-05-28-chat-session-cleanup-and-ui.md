# Chat Session Cleanup and Chat UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe chat session deletion with backend cleanup, then refresh the chat UI for a cleaner ChatGPT-like layout and prompt behavior.

**Architecture:** Keep the existing FastAPI + SQLModel backend and the existing React + Vite chat route. Add one explicit deletion API for chat sessions that clears DB rows, Redis cache keys, and attachment files. On the frontend, wire a lightweight delete action into the session list and keep the active session state synchronized so deleted sessions cannot be reopened from stale local state.

**Tech Stack:** FastAPI, SQLModel, Redis, React, TypeScript, Vite, SSE streaming chat.

---

### Task 1: Backend session deletion and cleanup

**Files:**
- Modify: `backend/app/gwy/services/chat_session_service.py`
- Modify: `backend/app/api/routes/gwy.py`
- Modify: `backend/tests/api/routes/test_gwy.py`

- [ ] **Step 1: Write the failing test**

Add a route test that creates a chat session, uploads or inserts at least one message and attachment row, calls `DELETE /api/v1/gwy/chat/sessions/{session_id}`, and asserts the session, messages, attachments, conversation memory, and session-scoped RAG cache entries are gone.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/api/routes/test_gwy.py -q -k chat_session`
Expected: fail because the delete route does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add `delete_session()` to `ChatSessionService` to:
1. load and validate the session,
2. collect attachment file paths,
3. delete `GwyChatMessage`, `GwyChatAttachment`, `GwyConversationMemory`, `GwyRagCacheEntry`, and `GwyChatSession`,
4. remove matching Redis keys using `gwy:rag:{query_hash}`,
5. delete attachment files and empty upload folders best-effort.

Add a `DELETE /chat/sessions/{session_id}` route that calls the service and returns a simple success message.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/api/routes/test_gwy.py -q -k chat_session`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/chat_session_service.py backend/app/api/routes/gwy.py backend/tests/api/routes/test_gwy.py
git commit -m "feat: delete chat sessions with cleanup"
```

### Task 2: Rewrite chat prompts and answer rules

**Files:**
- Modify: `backend/app/gwy/prompts/policy_rag.py`
- Modify: `backend/app/gwy/services/policy_rag_service.py`
- Modify: `backend/tests/gwy/test_policy_rag_service.py`

- [ ] **Step 1: Write the failing test**

Add a test that asserts the prompt strings expose the requested sections: role, tone, capabilities, answer rules, retrieval conditions, and direct-answer conditions, and that the direct-answer branch remains free of markdown-heavy formatting.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_policy_rag_service.py -q`
Expected: fail until the rewritten prompts and any normalization tweaks are in place.

- [ ] **Step 3: Write minimal implementation**

Replace the current prompt blobs with a structured prompt that:
1. defines the assistant role and tone,
2. enumerates supported capabilities,
3. states answer format rules clearly,
4. says when to retrieve and when to answer directly,
5. tells the model to avoid `*` and noisy Markdown in final output.

Keep the existing intent routing and streaming split intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_policy_rag_service.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/prompts/policy_rag.py backend/app/gwy/services/policy_rag_service.py backend/tests/gwy/test_policy_rag_service.py
git commit -m "feat: clarify chat prompts and answer rules"
```

### Task 3: Frontend session deletion and layout refresh

**Files:**
- Modify: `frontend/src/routes/_layout/gwy/chat.tsx`

- [ ] **Step 1: Write the failing test**

If the project has no direct component test for this route, add a small regression test or at least a typed check path that covers deleting a session and rendering user messages on the right and assistant messages on the left.

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run --filter frontend lint`
Expected: fail until the delete handler and layout adjustments are implemented.

- [ ] **Step 3: Write minimal implementation**

Add a delete button per session row, call the new delete API, remove the deleted session from local state, and safely switch `activeSessionId` if the current session was deleted.

Update the message layout so assistant and user messages are visually distinct, aligned left/right, and the top header and empty state share a single minimal visual language.

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run --filter frontend lint`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout/gwy/chat.tsx
git commit -m "feat: refresh chat layout and session deletion"
```

