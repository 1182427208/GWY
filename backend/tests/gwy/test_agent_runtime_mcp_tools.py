from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.gwy.agent_runtime import ToolContext, ToolRegistry
from app.gwy.agent_runtime.builtin_tools import register_builtin_tools
from app.gwy.agent_runtime.permissions import check_permission
from app.gwy.services.autonomous_chat_agent_service import (
    AUTONOMOUS_AGENT_SYSTEM_PROMPT,
    MCP_TOOL_PRIORITY_PROMPT as AUTONOMOUS_MCP_TOOL_PRIORITY_PROMPT,
)
from app.gwy.services.position_snapshot_runtime_service import (
    MCP_TOOL_PRIORITY_PROMPT as SNAPSHOT_MCP_TOOL_PRIORITY_PROMPT,
    POSITION_SNAPSHOT_SYSTEM_PROMPT,
)
from app.gwy.services.db_mcp_client import DatabaseMCPClient
from app.gwy.services.web_mcp_client import WebMCPClient


def test_builtin_tools_register_web_and_db_mcp_tools(monkeypatch) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(settings, "DB_MCP_URL", "http://db-mcp:8002/mcp")

    registry = ToolRegistry()
    register_builtin_tools(registry)

    for name in {
        "web_search",
        "web_fetch",
        "browser_retrieve",
        "verify_web_evidence",
        "list_tables",
        "describe_table",
        "sample_rows",
        "query_sql",
    }:
        assert registry.get(name) is not None


def test_web_mcp_runtime_tools_delegate_to_client(monkeypatch) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(
        WebMCPClient,
        "search",
        lambda self, query, top_k=5: {
            "query": query,
            "count": 1,
            "results": [
                {
                    "title": "Remote Search",
                    "url": "https://example.com/remote",
                    "snippet": "Remote snippet",
                    "source": "web_mcp",
                }
            ],
        },
    )
    monkeypatch.setattr(
        WebMCPClient,
        "fetch",
        lambda self, url, max_chars=20000: {
            "url": url,
            "title": "Remote Title",
            "text": "Remote body",
            "retrieved_via": "fetch_mcp",
        },
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)
    context = ToolContext(state={})

    search = registry.get("web_search")
    fetch = registry.get("web_fetch")
    assert search is not None
    assert fetch is not None

    search_result = search.handler({"query": "中央办公厅", "max_results": 1}, context)
    fetch_result = fetch.handler({"url": "https://example.com/remote"}, context)

    assert search_result["results"][0]["title"] == "Remote Search"
    assert fetch_result["title"] == "Remote Title"
    assert fetch_result["retrieved_via"] == "fetch_mcp"


def test_db_mcp_runtime_tools_delegate_to_client(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DB_MCP_URL", "http://db-mcp:8002/mcp")
    monkeypatch.setattr(
        DatabaseMCPClient,
        "list_tables",
        lambda self: {"tables": ["positions"], "count": 1, "schema_count": 1},
    )
    monkeypatch.setattr(
        DatabaseMCPClient,
        "query_sql",
        lambda self, sql, limit=50: {
            "sql": sql,
            "limit": limit,
            "row_count": 1,
            "columns": ["id"],
            "rows": [{"id": 1}],
        },
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)
    context = ToolContext(state={})

    list_tables = registry.get("list_tables")
    query_sql = registry.get("query_sql")
    assert list_tables is not None
    assert query_sql is not None

    listed = list_tables.handler({}, context)
    queried = query_sql.handler({"sql": "SELECT id FROM positions", "limit": 1}, context)

    assert listed["count"] == 1
    assert queried["columns"] == ["id"]


def test_mcp_runtime_tools_are_allowed_by_permissions() -> None:
    for tool_name in {
        "web_search",
        "web_fetch",
        "browser_retrieve",
        "verify_web_evidence",
        "list_tables",
        "describe_table",
        "sample_rows",
        "query_sql",
    }:
        decision = check_permission(tool_name, {})
        assert decision.behavior == "allow"


def test_system_prompts_include_mcp_priority_guidance() -> None:
    assert AUTONOMOUS_MCP_TOOL_PRIORITY_PROMPT in AUTONOMOUS_AGENT_SYSTEM_PROMPT
    assert SNAPSHOT_MCP_TOOL_PRIORITY_PROMPT in POSITION_SNAPSHOT_SYSTEM_PROMPT
    assert "web_search" in AUTONOMOUS_AGENT_SYSTEM_PROMPT
    assert "query_sql" in POSITION_SNAPSHOT_SYSTEM_PROMPT
