from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP


MCP_HOST = "127.0.0.1"
MCP_PORT = 8931
MCP_STREAMABLE_HTTP_PATH = "/mcp"
MCP_SSE_PATH = "/sse"

mcp = FastMCP(
    "gwy-playwright",
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_STREAMABLE_HTTP_PATH,
    sse_path=MCP_SSE_PATH,
)


@mcp.tool()
async def read_page(url: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return {
            "ok": False,
            "url": "",
            "error": "url is required",
            "source": "playwright",
            "retrieved_via": "playwright_server",
        }

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - import guard
        return {
            "ok": False,
            "url": normalized_url,
            "error": f"playwright import failed: {exc}",
            "source": "playwright",
            "retrieved_via": "playwright_server",
        }

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(
                    normalized_url,
                    wait_until="domcontentloaded",
                    timeout=int(timeout_seconds * 1000),
                )
                try:
                    await page.wait_for_load_state(
                        "networkidle",
                        timeout=int(timeout_seconds * 1000),
                    )
                except Exception:
                    pass

                title = _first_text(await page.title())
                text = await _read_visible_text(page, timeout_seconds=timeout_seconds)

                return {
                    "ok": True,
                    "url": normalized_url,
                    "final_url": str(page.url or normalized_url),
                    "title": title,
                    "text": text,
                    "content_type": "text/html",
                    "source": "playwright",
                    "retrieved_via": "playwright_server",
                    "text_length": len(text),
                }
            finally:
                await browser.close()
    except Exception as exc:
        return {
            "ok": False,
            "url": normalized_url,
            "error": str(exc),
            "source": "playwright",
            "retrieved_via": "playwright_server",
        }


async def _read_visible_text(page: Any, *, timeout_seconds: float) -> str:
    try:
        text = str(
            await page.locator("body").inner_text(timeout=int(timeout_seconds * 1000))
            or ""
        )
    except Exception:
        text = str(await page.content() or "")
    return _normalize_text(text)


def _normalize_text(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
