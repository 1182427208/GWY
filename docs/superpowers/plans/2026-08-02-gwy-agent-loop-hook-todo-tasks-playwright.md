# GwyPilot Agent Loop Hook / todo_tasks / Playwright MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local Playwright MCP server entrypoint, promote `todo_tasks` as the visible planning tool name, and make hook logs show subagent execution, tool usage, and web補证 details without changing the existing agent loop architecture.

**Architecture:** Keep `AgentRuntime` as the main loop and keep current tools, permissions, and recovery behavior intact. Add a compatibility alias so `todo_tasks` becomes the new standard planning tool while `todo_write` remains supported. Extend trace emission only at the boundaries where subagents are invoked so the hook can render a richer execution story: main loop → subagent call → tools used → web evidence gathered → subagent result.

**Tech Stack:** Python 3.10+, FastAPI template backend, LangGraph-based agents, MCP `FastMCP`, pytest, existing runtime trace/logging.

## Global Constraints

- Preserve the `fastapi/full-stack-fastapi-template` skeleton; do not restructure the app layout.
- Keep PostgreSQL for structured positions and Milvus for policy / guide RAG.
- Keep the current tool, permission, and exception handling behavior unchanged except for the new alias and added trace visibility.
- Do not add frontend pages.
- Prefer `backend/app/gwy/` for new backend code.
- Web retrieval must continue to support: SearXNG search, HTTP fetch, and Playwright-based rendering.

---

### Task 1: Introduce `todo_tasks` as the visible planning tool and keep `todo_write` as a compatibility alias

**Files:**
- Modify: `backend/app/gwy/agent_runtime/builtin_tools.py`
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
- Modify: `backend/app/gwy/services/position_snapshot_runtime_service.py`
- Modify: `backend/app/gwy/runtime_skills/position-planning/SKILL.md`
- Modify: `backend/app/gwy/README.md`
- Test: `backend/tests/gwy/test_agent_runtime_task_contract.py`

**Interfaces:**
- Consumes: `register_builtin_tools()`, `ToolRegistry.get()`, `ToolSpec`, `TaskContract.from_todos()`
- Produces: a registered `todo_tasks` tool that shares the existing todo payload contract with `todo_write`

- [ ] **Step 1: Write the failing test**

```python
from app.gwy.agent_runtime import ToolRegistry
from app.gwy.agent_runtime.builtin_tools import register_builtin_tools


def test_todo_tasks_is_registered_and_behaves_like_todo_write() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)

    todo_tasks = registry.get("todo_tasks")
    todo_write = registry.get("todo_write")

    assert todo_tasks is not None
    assert todo_write is not None

    context = ToolContext(state={})
    output = todo_tasks.handler(
        {"todos": [{"content": "先做岗位筛选", "status": "pending"}]},
        context,
    )

    assert output["count"] == 1
    assert context.state["task_contract"]["todos"][0]["content"] == "先做岗位筛选"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_agent_runtime_task_contract.py -v`
Expected: fail until `todo_tasks` is registered.

- [ ] **Step 3: Write minimal implementation**

Register one shared handler under both names. Update system prompts and runtime skills to mention `todo_tasks` first, but keep `todo_write` compatible. Update the README startup notes to mention the new preferred name and explain that `todo_write` is legacy-compatible.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_agent_runtime_task_contract.py -v`
Expected: pass with both tool names available.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/agent_runtime/builtin_tools.py backend/app/gwy/services/autonomous_chat_agent_service.py backend/app/gwy/services/position_snapshot_runtime_service.py backend/app/gwy/runtime_skills/position-planning/SKILL.md backend/app/gwy/README.md backend/tests/gwy/test_agent_runtime_task_contract.py
git commit -m "feat: promote todo_tasks alias"
```

### Task 2: Add richer hook trace events for subagent calls and web evidence gathering

**Files:**
- Modify: `backend/app/gwy/agent_runtime/loop.py`
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
- Modify: `backend/app/gwy/agents/position_analysis_agent.py`
- Modify: `backend/app/gwy/agents/web_verification_agent.py`
- Modify: `backend/app/gwy/services/web_research_service.py`
- Modify: `backend/tests/gwy/test_agent_runtime_task_contract.py`
- Add: `backend/tests/gwy/test_agent_runtime_hooks.py`

**Interfaces:**
- Consumes: `TraceEvent`, `ToolContext.record_event()`, existing agent `run()` return payloads with `trace`, `web_search_attempts`, `web_results`
- Produces: new hook-visible trace events such as `SubAgentStart`, `SubAgentEnd`, `SubAgentToolUse`, and `WebResearchStep`

- [ ] **Step 1: Write the failing test**

```python
def test_hook_formats_subagent_and_web_events(caplog):
    runtime = AgentRuntime(...)
    event = TraceEvent(
        event="SubAgentStart",
        status="running",
        step="position_analysis",
        tool="position_analysis",
        detail="Creating position analysis subagent.",
        input={"query": "报录比"},
    )

    runtime._log_hook_event(event, TraceRecorder())

    assert "SubAgentStart" in caplog.text
    assert "position_analysis" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_agent_runtime_hooks.py -v`
Expected: fail until the hook understands the new event types.

- [ ] **Step 3: Write minimal implementation**

Add helper methods in `autonomous_chat_agent_service.py` so the tool wrapper records:
- subagent start / end
- tool list or tool summary
- missing-content detection
- web search / fetch / browser fallback summaries from returned traces

Update `_log_hook_event()` so it prints these events in a compact human-readable form. Reuse the existing `TraceEvent` shape; do not change permissions or the main runtime control flow.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_agent_runtime_hooks.py -v`
Expected: pass and show the new hook text.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/agent_runtime/loop.py backend/app/gwy/services/autonomous_chat_agent_service.py backend/app/gwy/agents/position_analysis_agent.py backend/app/gwy/agents/web_verification_agent.py backend/app/gwy/services/web_research_service.py backend/tests/gwy/test_agent_runtime_hooks.py
git commit -m "feat: enrich agent loop hook traces"
```

### Task 3: Document the local Playwright MCP server startup path

**Files:**
- Modify: `backend/app/gwy/README.md`
- Modify: `backend/.env.example` if present and relevant

**Interfaces:**
- Consumes: `backend/app/gwy/mcp_tools/playwright_server.py`
- Produces: startup instructions that point `PLAYWRIGHT_MCP_URL` to `http://localhost:8931/mcp`

- [ ] **Step 1: Write the failing doc check**

```python
def test_readme_mentions_playwright_mcp_startup():
    text = Path("backend/app/gwy/README.md").read_text(encoding="utf-8")
    assert "python -m app.gwy.mcp_tools.playwright_server" in text
    assert "PLAYWRIGHT_MCP_URL=http://localhost:8931/mcp" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/gwy/test_readme_docs.py -v`
Expected: fail until the startup instructions are written.

- [ ] **Step 3: Write minimal implementation**

Add a short “Web Retrieval Startup” section that shows:
- how to launch the local Playwright MCP server
- the default port and endpoint
- that `todo_write` is legacy-compatible, but `todo_tasks` is the preferred planning tool name

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/gwy/test_readme_docs.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/README.md backend/.env.example backend/tests/gwy/test_readme_docs.py
git commit -m "docs: add local playwright mcp startup guide"
```

### Task 4: Verify the end-to-end runtime behavior

**Files:**
- No new files; run focused tests and a smoke check

**Interfaces:**
- Consumes: `todo_tasks`, hook trace events, `PlaywrightMCPService(endpoint_url="http://localhost:8931/mcp")`
- Produces: verified runtime output showing the new alias and richer hook logs

- [ ] **Step 1: Run the focused runtime tests**

Run:
`pytest backend/tests/gwy/test_agent_runtime_task_contract.py backend/tests/gwy/test_agent_runtime_hooks.py backend/tests/gwy/test_web_retrieval_services.py -v`

Expected: all tests pass.

- [ ] **Step 2: Smoke-test the local Playwright MCP server**

Run:
`python -m app.gwy.mcp_tools.playwright_server`

Then in another shell:
`python - <<'PY'
from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
print(PlaywrightMCPService(endpoint_url="http://localhost:8931/mcp").read("https://www.gov.cn/")["retrieved_via"])
PY`

Expected: `playwright_mcp:read_page`

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "feat: surface subagent and web evidence hooks"
```

## Self-Review Checklist

- [ ] `todo_tasks` is the preferred visible planning tool name and `todo_write` still works.
- [ ] Hook output now shows subagent creation, tool usage, and web evidence gathering.
- [ ] The Playwright MCP startup path is documented.
- [ ] No tool, permission, or exception-handling behavior was removed.
- [ ] All tests added in the plan reference real file paths and executable commands.
