from __future__ import annotations

from typing import Any, Callable

from app.gwy.agent_runtime.tools import ToolRegistry, ToolSpec
from app.gwy.services.db_mcp_client import DatabaseMCPClient
from app.gwy.services.web_mcp_client import WebMCPClient


def register_mcp_tools(registry: ToolRegistry) -> None:
    register_web_mcp_tools(registry)
    register_db_mcp_tools(registry)


def register_web_mcp_tools(registry: ToolRegistry) -> None:
    registry.register(
        _tool(
            name="web_search",
            description=(
                "Search public web evidence through the unified Web MCP server."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
            },
            handler=_run_web_search,
        )
    )
    registry.register(
        _tool(
            name="web_fetch",
            description="Fetch readable text from a public web page through Web MCP.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 100000,
                    },
                },
                "required": ["url"],
            },
            handler=_run_web_fetch,
        )
    )
    registry.register(
        _tool(
            name="browser_retrieve",
            description=(
                "Render a public page with browser automation through Web MCP."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "selector": {"type": "string"},
                    "wait_ms": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 100000,
                    },
                },
                "required": ["url"],
            },
            handler=_run_browser_retrieve,
        )
    )
    registry.register(
        _tool(
            name="verify_web_evidence",
            description=(
                "Verify whether a public page contains the requested evidence."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "planned_queries": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "seed_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["query"],
            },
            handler=_run_verify_web_evidence,
        )
    )


def register_db_mcp_tools(registry: ToolRegistry) -> None:
    registry.register(
        _tool(
            name="list_tables",
            description="List database tables through the read-only DB MCP server.",
            parameters={"type": "object", "properties": {}},
            handler=_run_list_tables,
        )
    )
    registry.register(
        _tool(
            name="describe_table",
            description="Describe the columns and primary key of a database table.",
            parameters={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                },
                "required": ["table_name"],
            },
            handler=_run_describe_table,
        )
    )
    registry.register(
        _tool(
            name="sample_rows",
            description="Return a small sample of rows from a database table.",
            parameters={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["table_name"],
            },
            handler=_run_sample_rows,
        )
    )
    registry.register(
        _tool(
            name="query_sql",
            description=(
                "Run a read-only SELECT or WITH query through the DB MCP server."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["sql"],
            },
            handler=_run_query_sql,
        )
    )


def _tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: Callable[[dict[str, Any], Any], dict[str, Any]],
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
    )


def _run_web_search(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    top_k = _int_arg(args.get("max_results"), default=5, minimum=1, maximum=20)
    client = WebMCPClient()
    if not client.is_available():
        return _unavailable("web_search", "WEB_MCP_URL is not configured.")
    result = client.search(query, top_k=top_k)
    return result or _unavailable("web_search", "Web MCP search returned no result.")


def _run_web_fetch(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    max_chars = _int_arg(args.get("max_chars"), default=20_000, minimum=1000, maximum=100000)
    client = WebMCPClient()
    if not client.is_available():
        return _unavailable("web_fetch", "WEB_MCP_URL is not configured.", url=url)
    result = client.fetch(url, max_chars=max_chars)
    return result or _unavailable("web_fetch", "Web MCP fetch returned no result.", url=url)


def _run_browser_retrieve(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    selector = str(args.get("selector") or "body").strip() or "body"
    wait_ms = _int_arg(args.get("wait_ms"), default=800, minimum=0, maximum=10000)
    max_chars = _int_arg(args.get("max_chars"), default=20_000, minimum=1000, maximum=100000)
    client = WebMCPClient()
    if not client.is_available():
        return _unavailable(
            "browser_retrieve",
            "WEB_MCP_URL is not configured.",
            url=url,
        )
    result = client.read(
        url,
        selector=selector,
        wait_ms=wait_ms,
        max_chars=max_chars,
    )
    return result or _unavailable(
        "browser_retrieve",
        "Web MCP browser retrieval returned no result.",
        url=url,
    )


def _run_verify_web_evidence(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    planned_queries = [
        str(item).strip()
        for item in list(args.get("planned_queries") or [])
        if str(item).strip()
    ]
    seed_urls = [
        str(item).strip()
        for item in list(args.get("seed_urls") or [])
        if str(item).strip()
    ]
    top_k = _int_arg(args.get("top_k"), default=3, minimum=1, maximum=10)
    client = WebMCPClient()
    if not client.is_available():
        return _unavailable(
            "verify_web_evidence",
            "WEB_MCP_URL is not configured.",
        )
    result = client.verify(
        query=query,
        planned_queries=planned_queries,
        top_k=top_k,
        seed_urls=seed_urls,
    )
    return result or _unavailable(
        "verify_web_evidence",
        "Web MCP verification returned no result.",
    )


def _run_list_tables(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    del args
    client = DatabaseMCPClient()
    if not client.is_available():
        return _unavailable("list_tables", "DB_MCP_URL is not configured.")
    result = client.list_tables()
    return result or _unavailable("list_tables", "DB MCP returned no result.")


def _run_describe_table(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    table_name = str(args.get("table_name") or "").strip()
    client = DatabaseMCPClient()
    if not client.is_available():
        return _unavailable("describe_table", "DB_MCP_URL is not configured.", table_name=table_name)
    result = client.describe_table(table_name)
    return result or _unavailable("describe_table", "DB MCP returned no result.", table_name=table_name)


def _run_sample_rows(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    table_name = str(args.get("table_name") or "").strip()
    limit = _int_arg(args.get("limit"), default=5, minimum=1, maximum=100)
    client = DatabaseMCPClient()
    if not client.is_available():
        return _unavailable("sample_rows", "DB_MCP_URL is not configured.", table_name=table_name)
    result = client.sample_rows(table_name, limit=limit)
    return result or _unavailable("sample_rows", "DB MCP returned no result.", table_name=table_name)


def _run_query_sql(args: dict[str, Any], _context: Any) -> dict[str, Any]:
    sql = str(args.get("sql") or "").strip()
    limit = _int_arg(args.get("limit"), default=50, minimum=1, maximum=200)
    client = DatabaseMCPClient()
    if not client.is_available():
        return _unavailable("query_sql", "DB_MCP_URL is not configured.")
    result = client.query_sql(sql, limit=limit)
    return result or _unavailable("query_sql", "DB MCP returned no result.")


def _int_arg(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _unavailable(tool: str, error: str, **extra: Any) -> dict[str, Any]:
    payload = {"ok": False, "tool": tool, "error": error}
    payload.update({key: value for key, value in extra.items() if value not in (None, "")})
    return payload
