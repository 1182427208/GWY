from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import MetaData, Table, inspect, select, text

from app.core.db import engine


MCP_HOST = "127.0.0.1"
MCP_PORT = 8002
MCP_STREAMABLE_HTTP_PATH = "/mcp"
MCP_SSE_PATH = "/sse"

mcp = FastMCP(
    "gwy-db",
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_STREAMABLE_HTTP_PATH,
    sse_path=MCP_SSE_PATH,
)


def _normalize_limit(value: Any, *, default: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, max_value))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date, Decimal)):
        return str(value)
    return value


def _to_row_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(_jsonable(dict(row)))
    return normalized


def _resolve_engine(db_engine: Any | None = None) -> Any:
    return db_engine or engine


def _table(table_name: str, db_engine: Any | None = None) -> Table:
    current_engine = _resolve_engine(db_engine)
    metadata = MetaData()
    try:
        return Table(table_name, metadata, autoload_with=current_engine)
    except Exception as exc:
        raise ValueError(f"unknown table: {table_name}") from exc


def _list_tables(db_engine: Any | None = None) -> dict[str, Any]:
    current_engine = _resolve_engine(db_engine)
    inspector = inspect(current_engine)
    table_names = sorted(inspector.get_table_names())
    return {
        "tables": table_names,
        "count": len(table_names),
        "schema_count": len(inspector.get_schema_names()),
    }


def _describe_table(table_name: str, db_engine: Any | None = None) -> dict[str, Any]:
    current_engine = _resolve_engine(db_engine)
    table = _table(table_name, current_engine)
    inspector = inspect(current_engine)
    columns: list[dict[str, Any]] = []
    primary_key = {column.name for column in table.primary_key.columns}
    for column in inspector.get_columns(table_name):
        columns.append(
            {
                "name": column.get("name"),
                "type": str(column.get("type")),
                "nullable": bool(column.get("nullable", True)),
                "default": _jsonable(column.get("default")),
                "primary_key": column.get("name") in primary_key,
            }
        )
    return {
        "table_name": table_name,
        "columns": columns,
        "column_count": len(columns),
        "primary_key_columns": sorted(primary_key),
    }


def _sample_rows(table_name: str, limit: int = 5, db_engine: Any | None = None) -> dict[str, Any]:
    current_engine = _resolve_engine(db_engine)
    table = _table(table_name, current_engine)
    safe_limit = _normalize_limit(limit, default=5, max_value=100)
    stmt = select(table).limit(safe_limit)
    with current_engine.connect() as connection:
        rows = connection.execute(stmt).mappings().all()
    return {
        "table_name": table_name,
        "limit": safe_limit,
        "row_count": len(rows),
        "rows": _to_row_dicts(rows),
    }


def _is_readonly_sql(sql: str) -> bool:
    normalized = str(sql or "").strip().rstrip(";").strip()
    if not normalized:
        return False
    if ";" in normalized:
        return False
    lowered = normalized.lstrip().lower()
    return lowered.startswith("select") or lowered.startswith("with")


def _query_sql(sql: str, limit: int = 50, db_engine: Any | None = None) -> dict[str, Any]:
    current_engine = _resolve_engine(db_engine)
    normalized_sql = str(sql or "").strip().rstrip(";").strip()
    if not _is_readonly_sql(normalized_sql):
        raise ValueError("only single SELECT or WITH statements are allowed")

    safe_limit = _normalize_limit(limit, default=50, max_value=200)
    wrapped_sql = f"SELECT * FROM ({normalized_sql}) AS gwy_mcp_query LIMIT :limit"
    with current_engine.connect() as connection:
        result = connection.execute(text(wrapped_sql), {"limit": safe_limit})
        rows = result.mappings().all()
        columns = list(result.keys())
    return {
        "sql": normalized_sql,
        "limit": safe_limit,
        "row_count": len(rows),
        "columns": list(columns),
        "rows": _to_row_dicts(rows),
    }


@mcp.tool()
async def list_tables() -> dict[str, Any]:
    return _list_tables()


@mcp.tool()
async def describe_table(table_name: str) -> dict[str, Any]:
    return _describe_table(str(table_name or "").strip())


@mcp.tool()
async def sample_rows(table_name: str, limit: int = 5) -> dict[str, Any]:
    return _sample_rows(str(table_name or "").strip(), limit=limit)


@mcp.tool()
async def query_sql(sql: str, limit: int = 50) -> dict[str, Any]:
    return _query_sql(sql, limit=limit)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
