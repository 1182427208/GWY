from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
from app.gwy.services.web_fetch_service import WebFetchService
from app.gwy.services.web_research_service import WebResearchRequest, WebResearchService
from app.gwy.services.web_search_service import WebSearchService


MCP_HOST = "127.0.0.1"
MCP_PORT = 8001
MCP_STREAMABLE_HTTP_PATH = "/mcp"
MCP_SSE_PATH = "/sse"

mcp = FastMCP(
    "gwy-web",
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_STREAMABLE_HTTP_PATH,
    sse_path=MCP_SSE_PATH,
)

_LOCAL_SEARCH_SERVICE = WebSearchService(web_mcp_enabled=False)
_LOCAL_FETCH_SERVICE = WebFetchService(mcp_url="", web_mcp_enabled=False)
_LOCAL_BROWSER_SERVICE = PlaywrightMCPService(endpoint_url="", web_mcp_enabled=False)
_LOCAL_RESEARCH_SERVICE = WebResearchService(
    search_service=_LOCAL_SEARCH_SERVICE,
    fetch_service=_LOCAL_FETCH_SERVICE,
    browser_service=_LOCAL_BROWSER_SERVICE,
    web_mcp_enabled=False,
)


@mcp.tool()
async def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    results = _LOCAL_SEARCH_SERVICE.search(query, top_k=max_results)
    return {"query": query, "count": len(results), "results": results}


@mcp.tool()
async def web_fetch(url: str, max_chars: int = 20_000) -> dict[str, Any]:
    return _LOCAL_FETCH_SERVICE.fetch(url)


@mcp.tool()
async def browser_retrieve(
    url: str,
    selector: str = "body",
    wait_ms: int = 800,
    max_chars: int = 20_000,
) -> dict[str, Any]:
    return _LOCAL_BROWSER_SERVICE.read(
        url,
        selector=selector,
        wait_ms=wait_ms,
        max_chars=max_chars,
    )


@mcp.tool()
async def verify_web_evidence(
    query: str,
    planned_queries: list[str] | None = None,
    top_k: int = 3,
    seed_urls: list[str] | None = None,
) -> dict[str, Any]:
    result = _LOCAL_RESEARCH_SERVICE.verify(
        WebResearchRequest(
            query=query,
            planned_queries=list(planned_queries or []),
            seed_urls=list(seed_urls or []),
            top_k=top_k,
        )
    )
    return result.as_dict()


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
