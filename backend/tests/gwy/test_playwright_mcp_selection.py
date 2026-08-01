from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.gwy.services.playwright_mcp_service import PlaywrightMCPService


@dataclass
class FakeTool:
    name: str
    description: str
    inputSchema: dict[str, Any]


def test_select_mcp_tool_prefers_required_url_schema() -> None:
    service = PlaywrightMCPService(enabled=False)
    tools = [
        FakeTool("click", "click an element", {"properties": {"selector": {}}}),
        FakeTool(
            "read_page",
            "read a page",
            {"properties": {"url": {"type": "string"}}, "required": ["url"]},
        ),
    ]

    assert service._select_mcp_tool_name(tools) == "read_page"
    assert service._build_mcp_arguments(tools, "read_page", "https://example.com") == {
        "url": "https://example.com"
    }


def test_select_mcp_tool_returns_none_without_url_input() -> None:
    service = PlaywrightMCPService(enabled=False)
    tools = [FakeTool("click", "click an element", {"properties": {"selector": {}}})]

    assert service._select_mcp_tool_name(tools) is None
