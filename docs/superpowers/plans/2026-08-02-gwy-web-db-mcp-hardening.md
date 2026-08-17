# Gwy Web and DB MCP Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Web MCP call chain more reliable, add a read-only DB MCP server for schema and data inspection, and document all MCP tools, protocols, inputs, outputs, and call patterns in one place.

**Architecture:** Keep the existing project structure intact. Web retrieval stays on the current unified Web MCP server, but the client path should be hardened so `search -> fetch -> browser -> verify` has predictable fallbacks and explicit tracing. Database access becomes a separate read-only Streamable HTTP MCP server that exposes safe introspection and SELECT-only querying over the existing SQLModel/PostgreSQL schema. The backend keeps using thin service wrappers so agents and tests can call MCP-backed capabilities without changing the rest of the runtime.

**Tech Stack:** FastAPI template backend, SQLModel, PostgreSQL, Streamable HTTP MCP (`mcp.server.fastmcp`, `mcp.ClientSession`), httpx, pytest.

---

### Task 1: Harden the Web MCP retrieval path

**Files:**
- Modify: `backend/app/gwy/services/web_mcp_client.py`
- Modify: `backend/app/gwy/services/web_search_service.py`
- Modify: `backend/app/gwy/services/web_fetch_service.py`
- Modify: `backend/app/gwy/services/playwright_mcp_service.py`
- Modify: `backend/app/gwy/services/web_research_service.py`
- Modify: `backend/app/gwy/mcp_tools/web_server.py`
- Modify: `backend/tests/gwy/test_web_retrieval_services.py`

- [ ] **Step 1: Add a failing test for a stable fallback chain**

```python
def test_web_research_service_prefers_unified_web_mcp(monkeypatch):
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(WebMCPClient, "search", lambda self, query, top_k=5: {"query": query, "results": []})
    monkeypatch.setattr(WebMCPClient, "fetch", lambda self, url, max_chars=20000: {"url": url, "text": "body", "retrieved_via": "fetch_mcp"})
    monkeypatch.setattr(WebMCPClient, "read", lambda self, url, selector="body", wait_ms=800, max_chars=20000: {"url": url, "text": "browser body", "retrieved_via": "web_mcp:browser_retrieve"})
```

- [ ] **Step 2: Run the targeted test and confirm the current behavior**

Run: `python -m pytest backend/tests/gwy/test_web_retrieval_services.py -q`

Expected: the new coverage should fail until the fallback chain and result normalization are in place.

- [ ] **Step 3: Implement the minimal hardening**

```python
class WebMCPClient:
    def _call_tool_sync(...):
        # try MCP once, then return {}
```

```python
class WebSearchService:
    # if WEB_MCP_URL is set but the remote search returns no results, fall back to the local search providers
```

```python
class WebResearchService:
    # keep the current trace format, but prefer the unified MCP server first and preserve local fallback behavior
```

- [ ] **Step 4: Run the targeted tests and confirm they pass**

Run:
`python -m pytest backend/tests/gwy/test_web_retrieval_services.py backend/tests/gwy/test_playwright_mcp_selection.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/web_mcp_client.py backend/app/gwy/services/web_search_service.py backend/app/gwy/services/web_fetch_service.py backend/app/gwy/services/playwright_mcp_service.py backend/app/gwy/services/web_research_service.py backend/app/gwy/mcp_tools/web_server.py backend/tests/gwy/test_web_retrieval_services.py
git commit -m "feat: harden unified web mcp retrieval"
```

### Task 2: Add a read-only DB MCP server and client

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/gwy/mcp_tools/db_server.py`
- Create: `backend/app/gwy/services/db_mcp_client.py`
- Modify: `backend/app/gwy/README.md`
- Create: `backend/tests/gwy/test_db_mcp_tools.py`
- Modify: `backend/tests/conftest.py` if test fixtures need shared engine helpers

- [ ] **Step 1: Write the failing tests for schema and SELECT-only access**

```python
def test_db_mcp_lists_tables_and_describes_columns(db):
    ...

def test_db_mcp_sample_rows_returns_limited_rows(db):
    ...

def test_db_mcp_query_sql_rejects_non_select_sql(db):
    ...
```

- [ ] **Step 2: Run the new DB MCP tests and confirm they fail**

Run: `python -m pytest backend/tests/gwy/test_db_mcp_tools.py -q`

Expected: failure because the DB MCP server/client do not exist yet.

- [ ] **Step 3: Implement the DB MCP server**

```python
@mcp.tool()
async def list_tables() -> dict[str, Any]:
    ...

@mcp.tool()
async def describe_table(table_name: str) -> dict[str, Any]:
    ...

@mcp.tool()
async def sample_rows(table_name: str, limit: int = 5) -> dict[str, Any]:
    ...

@mcp.tool()
async def query_sql(sql: str, limit: int = 50) -> dict[str, Any]:
    ...
```

Implementation rules:
- Only allow `SELECT` and `WITH` queries.
- Reject `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, and multi-statement input.
- Cap returned rows to a small safe maximum.
- Use SQLModel metadata plus SQLAlchemy inspection so the tools reflect the real Postgres schema.

- [ ] **Step 4: Implement the DB MCP client wrapper**

```python
class DatabaseMCPClient:
    def list_tables(self) -> dict[str, Any]: ...
    def describe_table(self, table_name: str) -> dict[str, Any]: ...
    def sample_rows(self, table_name: str, limit: int = 5) -> dict[str, Any]: ...
    def query_sql(self, sql: str, limit: int = 50) -> dict[str, Any]: ...
```

The client should mirror the Web MCP client pattern:
- connect via Streamable HTTP
- normalize `structuredContent` when present
- fall back to decoded text JSON when needed

- [ ] **Step 5: Run the DB MCP tests and a focused backend test subset**

Run:
`python -m pytest backend/tests/gwy/test_db_mcp_tools.py backend/tests/gwy/test_web_retrieval_services.py -q`

Expected: DB tests pass, Web tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/gwy/mcp_tools/db_server.py backend/app/gwy/services/db_mcp_client.py backend/tests/gwy/test_db_mcp_tools.py backend/app/gwy/README.md backend/tests/conftest.py
git commit -m "feat: add readonly db mcp tools"
```

### Task 3: Document the MCP inventory and call contracts

**Files:**
- Create: `docs/gwy-mcp-tools-reference.md`
- Modify: `backend/app/gwy/README.md`

- [ ] **Step 1: Write a failing documentation check**

```python
def test_mcp_reference_doc_mentions_web_and_db_tools():
    text = Path("docs/gwy-mcp-tools-reference.md").read_text(encoding="utf-8")
    assert "web_search" in text
    assert "query_sql" in text
    assert "Streamable HTTP" in text
```

- [ ] **Step 2: Write the reference document**

Document these sections:
- current MCP servers
- protocol used by each server
- tool list
- inputs and outputs for each tool
- example call flow for Web MCP
- example call flow for DB MCP
- notes on read-only DB access and safe SQL restrictions

- [ ] **Step 3: Update the backend README**

Add a short operator-facing summary:
- which MCP URL to set
- what each tool does
- which tools are safe for retrieval vs database inspection

- [ ] **Step 4: Run a quick doc sanity check**

Run:
`python -m pytest backend/tests/gwy/test_db_mcp_tools.py -q`

Expected: pass, plus the doc references should be present and accurate.

- [ ] **Step 5: Commit**

```bash
git add docs/gwy-mcp-tools-reference.md backend/app/gwy/README.md
git commit -m "docs: add mcp tool reference"
```

