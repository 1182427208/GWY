from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert
from sqlalchemy.pool import StaticPool

from app.gwy.mcp_tools import db_server
from app.gwy.services.db_mcp_client import DatabaseMCPClient


@pytest.fixture()
def sqlite_engine() -> Any:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    people = Table(
        "people",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(64), nullable=False),
        Column("role", String(64), nullable=False),
    )
    scores = Table(
        "scores",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("person_id", Integer, nullable=False),
        Column("value", Integer, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(people),
            [
                {"id": 1, "name": "Alice", "role": "analyst"},
                {"id": 2, "name": "Bob", "role": "editor"},
                {"id": 3, "name": "Cindy", "role": "reviewer"},
            ],
        )
        connection.execute(
            insert(scores),
            [
                {"id": 1, "person_id": 1, "value": 95},
                {"id": 2, "person_id": 2, "value": 88},
            ],
        )
    return engine


def test_list_tables_and_describe_table(sqlite_engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_server, "engine", sqlite_engine)

    listed = db_server._list_tables()
    assert listed["count"] == 2
    assert listed["tables"] == ["people", "scores"]

    described = db_server._describe_table("people", sqlite_engine)
    assert described["table_name"] == "people"
    assert described["column_count"] == 3
    assert described["primary_key_columns"] == ["id"]
    assert [column["name"] for column in described["columns"]] == ["id", "name", "role"]


def test_sample_rows_returns_limited_rows(sqlite_engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_server, "engine", sqlite_engine)

    sampled = db_server._sample_rows("people", limit=2, db_engine=sqlite_engine)
    assert sampled["table_name"] == "people"
    assert sampled["limit"] == 2
    assert sampled["row_count"] == 2
    assert [row["name"] for row in sampled["rows"]] == ["Alice", "Bob"]


def test_query_sql_allows_select_but_rejects_writes(
    sqlite_engine: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_server, "engine", sqlite_engine)

    queried = db_server._query_sql(
        "SELECT id, name FROM people ORDER BY id",
        limit=2,
        db_engine=sqlite_engine,
    )
    assert queried["limit"] == 2
    assert queried["row_count"] == 2
    assert queried["columns"] == ["id", "name"]
    assert [row["name"] for row in queried["rows"]] == ["Alice", "Bob"]

    with pytest.raises(ValueError, match="only single SELECT or WITH statements are allowed"):
        db_server._query_sql(
            "UPDATE people SET name = 'Mallory'",
            limit=2,
            db_engine=sqlite_engine,
        )


def test_db_mcp_client_builds_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DatabaseMCPClient(endpoint_url="http://127.0.0.1:8002/mcp", enabled=True)
    captured: dict[str, dict[str, Any]] = {}

    def fake_call(self: DatabaseMCPClient, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        captured[tool_name] = dict(arguments)
        return {"tool": tool_name, "arguments": arguments}

    monkeypatch.setattr(DatabaseMCPClient, "_call_tool_sync", fake_call)

    client.list_tables()
    client.describe_table("people")
    client.sample_rows("people", limit=3)
    client.query_sql("SELECT * FROM people", limit=4)

    assert captured["describe_table"]["table_name"] == "people"
    assert captured["sample_rows"]["limit"] == 3
    assert captured["query_sql"]["limit"] == 4
