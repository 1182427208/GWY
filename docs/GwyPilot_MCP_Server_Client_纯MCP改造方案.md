# GwyPilot MCP Server / Client 改造方案

> 本文只保留 MCP 相关内容，用于后续将 GwyPilot 的公网能力改造成独立 MCP 服务。
>
> 目标能力：
>
> - `web_search`：搜索引擎检索；
> - `web_fetch`：静态网页抓取；
> - `browser_retrieve`：动态网页 / JS 页面浏览器检索；
> - `verify_web_evidence`：远程网页证据核验。
>
> 项目侧通过统一 MCP Client Manager 连接 MCP Server，并将远程 MCP Tools 注册到现有 Tool Registry。

---

# 1. 推荐总体结构

```text
GwyPilot Backend
      │
      ↓
Tool Registry
      │
      ↓
MCP Tool Adapter
      │
      ↓
MCP Client Manager
      │
      ↓
Streamable HTTP
      │
      ↓
GwyPilot Web MCP Server
      │
      ├── web_search
      ├── web_fetch
      ├── browser_retrieve
      └── verify_web_evidence
             │
      ┌──────┴────────┐
      ↓               ↓
   SearXNG         Playwright
                      ↓
                   Chromium
```

建议只暴露一个配置：

```env
WEB_MCP_URL=http://web-mcp:8001/mcp
```

而不要继续拆成：

```env
FETCH_MCP_URL=
PLAYWRIGHT_MCP_URL=
```

---

# 2. 为什么建议一个 Web MCP Server

当前四个能力属于同一个 Web Retrieval / Evidence 领域：

```text
Search
Fetch
Browser
Evidence Verification
```

统一放到一个 MCP Server 的好处：

- 只维护一个 MCP 连接；
- 只需要一个 `WEB_MCP_URL`；
- 可以共享 `httpx.AsyncClient`；
- 可以共享一个常驻 Chromium；
- Tool Discovery 更简单；
- 后续 Trace 中仍可按 Tool 名区分；
- Docker 部署更简单。

未来如果 Browser 压力过大，可以再拆分：

```text
SearchFetch MCP
Browser MCP
```

第一版没必要。

---

# 3. 推荐目录结构

```text
gwy-pilot/
│
├── backend/
│   └── app/
│       └── gwy/
│           └── tools/
│               └── mcp/
│                   ├── schemas.py
│                   ├── manager.py
│                   └── adapter.py
│
├── mcp_servers/
│   └── web/
│       ├── server.py
│       ├── requirements.txt
│       └── Dockerfile
│
└── docker-compose.yml
```

---

# 4. MCP Server 依赖

```txt
mcp
httpx
playwright
trafilatura
beautifulsoup4
```

安装：

```bash
pip install mcp httpx playwright trafilatura beautifulsoup4
playwright install chromium
```

---

# 5. Web MCP Server 示例

文件：

```text
mcp_servers/web/server.py
```

```python
from __future__ import annotations

import ipaddress
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from playwright.async_api import Browser, Playwright, async_playwright


SEARXNG_URL = os.getenv(
    "SEARXNG_URL",
    "http://localhost:8080",
).rstrip("/")

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))

HTTP_TIMEOUT_SECONDS = float(
    os.getenv("WEB_HTTP_TIMEOUT", "20")
)

BROWSER_TIMEOUT_MS = int(
    os.getenv("WEB_BROWSER_TIMEOUT_MS", "30000")
)

DEFAULT_MAX_CHARS = 20_000
MAX_FETCH_BYTES = 2 * 1024 * 1024


@dataclass
class WebAppContext:
    http: httpx.AsyncClient
    playwright: Playwright
    browser: Browser


@asynccontextmanager
async def app_lifespan(
    _server: FastMCP,
) -> AsyncIterator[WebAppContext]:
    """
    MCP Server 生命周期内复用：
    - httpx AsyncClient
    - Playwright
    - Chromium Browser
    """
    http = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(
            HTTP_TIMEOUT_SECONDS
        ),
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; GwyPilotWebMCP/1.0)"
            )
        },
    )

    playwright = await async_playwright().start()

    browser = await playwright.chromium.launch(
        headless=True
    )

    try:
        yield WebAppContext(
            http=http,
            playwright=playwright,
            browser=browser,
        )

    finally:
        await browser.close()
        await playwright.stop()
        await http.aclose()


mcp = FastMCP(
    "GwyPilot Web MCP",
    lifespan=app_lifespan,
    stateless_http=True,
    json_response=True,
    host=MCP_HOST,
    port=MCP_PORT,
)


def validate_public_http_url(
    url: str,
) -> str:
    """
    基础 SSRF 防护。

    生产环境仍建议额外使用：
    - Docker Network
    - Firewall
    - Outbound Proxy
    """
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            "Only http/https URLs are allowed."
        )

    hostname = parsed.hostname

    if not hostname:
        raise ValueError(
            "URL hostname is missing."
        )

    lowered = hostname.lower()

    if (
        lowered == "localhost"
        or lowered.endswith(".local")
    ):
        raise ValueError(
            "Local hosts are forbidden."
        )

    try:
        ip = ipaddress.ip_address(hostname)

    except ValueError:
        ip = None

    if ip is not None:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                "Private/local IP is forbidden."
            )

    return url


def truncate(
    text: str,
    max_chars: int,
) -> str:
    max_chars = max(
        1000,
        min(max_chars, 100_000),
    )

    if len(text) <= max_chars:
        return text

    return (
        text[:max_chars]
        + "\n...[truncated]"
    )


def extract_readable_text(
    html: str,
) -> str:
    """
    优先使用 trafilatura 提取正文，
    失败时回退 BeautifulSoup。
    """
    extracted = trafilatura.extract(
        html,
        include_links=True,
        include_tables=True,
        output_format="txt",
    )

    if extracted and extracted.strip():
        return extracted.strip()

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "canvas",
        ]
    ):
        tag.decompose()

    lines = [
        line.strip()
        for line in soup.get_text(
            "\n"
        ).splitlines()
        if line.strip()
    ]

    return "\n".join(lines)


def make_snippets(
    text: str,
    terms: list[str],
    radius: int = 180,
    max_snippets: int = 8,
) -> list[str]:
    snippets: list[str] = []
    lower = text.lower()

    for term in terms:
        if not term:
            continue

        index = lower.find(
            term.lower()
        )

        if index < 0:
            continue

        start = max(
            0,
            index - radius,
        )

        end = min(
            len(text),
            index + len(term) + radius,
        )

        snippets.append(
            text[start:end].strip()
        )

        if len(snippets) >= max_snippets:
            break

    return snippets


async def fetch_text(
    app: WebAppContext,
    url: str,
    max_chars: int,
) -> dict[str, Any]:
    safe_url = validate_public_http_url(
        url
    )

    response = await app.http.get(
        safe_url
    )

    response.raise_for_status()

    content_type = response.headers.get(
        "content-type",
        "",
    )

    raw = response.content[
        :MAX_FETCH_BYTES
    ]

    encoding = (
        response.encoding
        or "utf-8"
    )

    html = raw.decode(
        encoding,
        errors="replace",
    )

    text = extract_readable_text(
        html
    )

    return {
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": content_type,
        "title": "",
        "text": truncate(
            text,
            max_chars,
        ),
        "retrieval_method": "http_fetch",
    }


async def browser_text(
    app: WebAppContext,
    url: str,
    selector: str,
    wait_ms: int,
    max_chars: int,
) -> dict[str, Any]:
    safe_url = validate_public_http_url(
        url
    )

    # Chromium 进程复用，但每次创建独立 Context
    context = await app.browser.new_context()

    try:
        page = await context.new_page()

        page.set_default_timeout(
            BROWSER_TIMEOUT_MS
        )

        await page.goto(
            safe_url,
            wait_until="domcontentloaded",
            timeout=BROWSER_TIMEOUT_MS,
        )

        if wait_ms > 0:
            await page.wait_for_timeout(
                min(
                    wait_ms,
                    10_000,
                )
            )

        title = await page.title()

        locator = page.locator(
            selector or "body"
        ).first

        text = await locator.inner_text(
            timeout=BROWSER_TIMEOUT_MS
        )

        return {
            "url": page.url,
            "status_code": None,
            "content_type": "text/html",
            "title": title,
            "text": truncate(
                text,
                max_chars,
            ),
            "retrieval_method": "playwright",
        }

    finally:
        await context.close()


@mcp.tool()
async def web_search(
    query: str,
    ctx: Context[
        ServerSession,
        WebAppContext,
    ],
    domains: list[str] | None = None,
    language: str = "zh-CN",
    max_results: int = 8,
) -> dict[str, Any]:
    """
    通过 SearXNG 搜索公网信息，
    主要用于发现候选 URL。
    """
    app = (
        ctx.request_context
        .lifespan_context
    )

    max_results = max(
        1,
        min(max_results, 20),
    )

    response = await app.http.get(
        f"{SEARXNG_URL}/search",
        params={
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": 1,
        },
    )

    response.raise_for_status()

    payload = response.json()

    allowed_domains = {
        item.lower().lstrip(".")
        for item in (domains or [])
        if item.strip()
    }

    results: list[
        dict[str, Any]
    ] = []

    for item in payload.get(
        "results",
        [],
    ):
        url = item.get("url")

        if not url:
            continue

        host = (
            urlparse(url).hostname
            or ""
        ).lower()

        if allowed_domains:
            if not any(
                host == domain
                or host.endswith(
                    "." + domain
                )
                for domain
                in allowed_domains
            ):
                continue

        results.append(
            {
                "title": item.get(
                    "title"
                ),
                "url": url,
                "snippet": (
                    item.get("content")
                    or item.get("snippet")
                    or ""
                ),
                "engine": item.get(
                    "engine"
                ),
                "published_date": (
                    item.get(
                        "publishedDate"
                    )
                    or item.get(
                        "published_date"
                    )
                ),
            }
        )

        if len(results) >= max_results:
            break

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


@mcp.tool()
async def web_fetch(
    url: str,
    ctx: Context[
        ServerSession,
        WebAppContext,
    ],
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """
    使用普通 HTTP 请求读取静态网页正文。
    """
    app = (
        ctx.request_context
        .lifespan_context
    )

    return await fetch_text(
        app=app,
        url=url,
        max_chars=max_chars,
    )


@mcp.tool()
async def browser_retrieve(
    url: str,
    ctx: Context[
        ServerSession,
        WebAppContext,
    ],
    selector: str = "body",
    wait_ms: int = 800,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """
    使用 Playwright 获取动态 / JS 网页内容。
    """
    app = (
        ctx.request_context
        .lifespan_context
    )

    return await browser_text(
        app=app,
        url=url,
        selector=selector,
        wait_ms=wait_ms,
        max_chars=max_chars,
    )


@mcp.tool()
async def verify_web_evidence(
    url: str,
    ctx: Context[
        ServerSession,
        WebAppContext,
    ],
    expected_terms: list[str] | None = None,
    expected_year: int | None = None,
    position_code: str | None = None,
    browser_fallback: bool = True,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """
    核验网页是否包含指定证据。

    注意：
    这里只检查页面与待核验字段是否匹配，
    不代表网页内容本身一定真实。
    """
    app = (
        ctx.request_context
        .lifespan_context
    )

    terms = [
        item.strip()
        for item in (
            expected_terms or []
        )
        if item and item.strip()
    ]

    fetch_error: str | None = None

    try:
        retrieved = await fetch_text(
            app=app,
            url=url,
            max_chars=max_chars,
        )

    except Exception as exc:
        fetch_error = repr(exc)

        if not browser_fallback:
            raise

        retrieved = await browser_text(
            app=app,
            url=url,
            selector="body",
            wait_ms=1000,
            max_chars=max_chars,
        )

    text = retrieved["text"]
    lower = text.lower()

    term_checks = {
        term: term.lower() in lower
        for term in terms
    }

    year_match = (
        True
        if expected_year is None
        else str(expected_year)
        in text
    )

    position_code_match = (
        True
        if not position_code
        else position_code.lower()
        in lower
    )

    evidence_match = (
        all(term_checks.values())
        and year_match
        and position_code_match
    )

    snippet_terms = list(
        terms
    )

    if expected_year is not None:
        snippet_terms.append(
            str(expected_year)
        )

    if position_code:
        snippet_terms.append(
            position_code
        )

    return {
        "url": retrieved["url"],
        "title": retrieved.get(
            "title",
            "",
        ),
        "retrieval_method": (
            retrieved[
                "retrieval_method"
            ]
        ),
        "evidence_match": (
            evidence_match
        ),
        "checks": {
            "term_checks": (
                term_checks
            ),
            "year_match": (
                year_match
            ),
            "position_code_match": (
                position_code_match
            ),
        },
        "snippets": make_snippets(
            text=text,
            terms=snippet_terms,
        ),
        "text": text,
        "fetch_error_before_fallback": (
            fetch_error
        ),
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http"
    )
```

---

# 6. MCP Server 生命周期建议

不要每次调用：

```text
browser_retrieve
```

都重新：

```text
async_playwright()
→ launch()
→ close()
```

正确方式：

```text
MCP Server 启动
→ Start Playwright
→ Launch Chromium
→ 保持 Chromium

每次调用
→ new BrowserContext
→ new Page
→ retrieve
→ close BrowserContext

MCP Server 关闭
→ close Chromium
```

这样可以显著降低 Browser Tool 延迟。

---

# 7. MCP Server 环境变量

```env
MCP_HOST=0.0.0.0
MCP_PORT=8001

SEARXNG_URL=http://searxng:8080

WEB_HTTP_TIMEOUT=20
WEB_BROWSER_TIMEOUT_MS=30000
```

---

# 8. MCP Client 配置结构

文件：

```text
backend/app/gwy/tools/mcp/schemas.py
```

```python
from dataclasses import dataclass, field


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    url: str
    enabled: bool = True
    headers: dict[str, str] = field(
        default_factory=dict
    )
    timeout_seconds: float = 60.0
```

---

# 9. MCP Client Manager

文件：

```text
backend/app/gwy/tools/mcp/manager.py
```

```python
from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import httpx
import mcp.types as mcp_types
from mcp import ClientSession
from mcp.client.streamable_http import (
    streamable_http_client,
)

from .schemas import MCPServerConfig


class MCPToolCallError(
    RuntimeError
):
    pass


@dataclass
class ConnectedMCPServer:
    config: MCPServerConfig
    stack: AsyncExitStack
    http_client: httpx.AsyncClient
    session: ClientSession
    tools: dict[
        str,
        mcp_types.Tool,
    ]


class MCPClientManager:
    """
    MCP 长生命周期 Client Manager。

    负责：
    - connect
    - initialize
    - list_tools
    - call_tool
    - reconnect
    - close
    """

    def __init__(
        self,
        configs: list[
            MCPServerConfig
        ],
    ) -> None:
        self._configs = {
            config.name: config
            for config in configs
            if config.enabled
        }

        self._servers: dict[
            str,
            ConnectedMCPServer,
        ] = {}

        self._locks: dict[
            str,
            asyncio.Lock,
        ] = {
            name: asyncio.Lock()
            for name in self._configs
        }

    async def start(
        self,
    ) -> None:
        for name in self._configs:
            await self.connect(
                name
            )

    async def close(
        self,
    ) -> None:
        for server in list(
            self._servers.values()
        ):
            await server.stack.aclose()

        self._servers.clear()

    async def connect(
        self,
        server_name: str,
    ) -> ConnectedMCPServer:
        if (
            server_name
            in self._servers
        ):
            return self._servers[
                server_name
            ]

        if (
            server_name
            not in self._configs
        ):
            raise KeyError(
                "Unknown MCP server: "
                f"{server_name}"
            )

        async with self._locks[
            server_name
        ]:
            if (
                server_name
                in self._servers
            ):
                return self._servers[
                    server_name
                ]

            config = self._configs[
                server_name
            ]

            stack = AsyncExitStack()

            try:
                http_client = (
                    httpx.AsyncClient(
                        headers=(
                            config.headers
                        ),
                        timeout=(
                            httpx.Timeout(
                                config.timeout_seconds
                            )
                        ),
                        follow_redirects=True,
                    )
                )

                await stack.enter_async_context(
                    http_client
                )

                transport = (
                    streamable_http_client(
                        url=config.url,
                        http_client=http_client,
                    )
                )

                (
                    read_stream,
                    write_stream,
                    _,
                ) = await stack.enter_async_context(
                    transport
                )

                session = (
                    await stack.enter_async_context(
                        ClientSession(
                            read_stream,
                            write_stream,
                        )
                    )
                )

                await session.initialize()

                await session.send_ping()

                tools_result = (
                    await session.list_tools()
                )

                tools = {
                    tool.name: tool
                    for tool
                    in tools_result.tools
                }

                connected = (
                    ConnectedMCPServer(
                        config=config,
                        stack=stack,
                        http_client=(
                            http_client
                        ),
                        session=session,
                        tools=tools,
                    )
                )

                self._servers[
                    server_name
                ] = connected

                return connected

            except Exception:
                await stack.aclose()
                raise

    async def disconnect(
        self,
        server_name: str,
    ) -> None:
        server = self._servers.pop(
            server_name,
            None,
        )

        if server:
            await server.stack.aclose()

    async def reconnect(
        self,
        server_name: str,
    ) -> ConnectedMCPServer:
        await self.disconnect(
            server_name
        )

        return await self.connect(
            server_name
        )

    async def list_tools(
        self,
        server_name: str,
    ) -> list[mcp_types.Tool]:
        server = await self.connect(
            server_name
        )

        return list(
            server.tools.values()
        )

    async def list_all_tools(
        self,
    ) -> dict[
        str,
        list[mcp_types.Tool],
    ]:
        result = {}

        for name in self._configs:
            result[name] = (
                await self.list_tools(
                    name
                )
            )

        return result

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[
            str,
            Any,
        ],
        retry_once: bool = True,
    ) -> dict[str, Any]:
        started = (
            time.perf_counter()
        )

        try:
            return await self._call_once(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                started=started,
            )

        except (
            httpx.TransportError,
            EOFError,
            ConnectionError,
        ) as exc:
            if not retry_once:
                raise MCPToolCallError(
                    "MCP transport failed: "
                    f"{exc!r}"
                ) from exc

            await self.reconnect(
                server_name
            )

            return await self._call_once(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                started=started,
            )

    async def _call_once(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[
            str,
            Any,
        ],
        started: float,
    ) -> dict[str, Any]:
        server = await self.connect(
            server_name
        )

        if (
            tool_name
            not in server.tools
        ):
            tools_result = (
                await server.session
                .list_tools()
            )

            server.tools = {
                tool.name: tool
                for tool
                in tools_result.tools
            }

        if (
            tool_name
            not in server.tools
        ):
            raise MCPToolCallError(
                f"Tool {tool_name!r} "
                "is not registered on "
                f"{server_name!r}"
            )

        result = (
            await server.session.call_tool(
                tool_name,
                arguments,
            )
        )

        latency_ms = int(
            (
                time.perf_counter()
                - started
            )
            * 1000
        )

        is_error = bool(
            getattr(
                result,
                "isError",
                False,
            )
        )

        structured_content = (
            getattr(
                result,
                "structuredContent",
                None,
            )
        )

        text_parts: list[str] = []

        for item in result.content:
            if isinstance(
                item,
                mcp_types.TextContent,
            ):
                text_parts.append(
                    item.text
                )

        normalized = {
            "server": server_name,
            "tool": tool_name,
            "arguments": arguments,
            "is_error": is_error,
            "structured_content": (
                structured_content
            ),
            "text": "\n".join(
                text_parts
            ),
            "latency_ms": latency_ms,
        }

        if is_error:
            raise MCPToolCallError(
                f"MCP tool failed: "
                f"{normalized}"
            )

        return normalized
```

---

# 10. 为什么需要 MCPClientManager

不要每次 Tool Call 都重新：

```text
connect
initialize
list_tools
call_tool
close
```

ReAct 一次执行可能是：

```text
web_search
→ web_fetch
→ browser_retrieve
→ verify_web_evidence
```

如果每次重新建立 Session，会增加不必要的：

```text
HTTP 开销
MCP 初始化开销
Tool Discovery 开销
```

因此推荐：

```text
Backend Startup
→ MCP Client Connect
→ Session Keep Alive
→ Tool Cache

Tool Call
→ 直接 call_tool

Backend Shutdown
→ close
```

---

# 11. MCP Tool Adapter

远程 MCP Tool 需要映射成当前 Agent Runtime 能理解的 Tool。

文件：

```text
backend/app/gwy/tools/mcp/adapter.py
```

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
)

import mcp.types as mcp_types

from .manager import (
    MCPClientManager,
)


ToolInvoke = Callable[
    [dict[str, Any]],
    Awaitable[
        dict[str, Any]
    ],
]


@dataclass
class RuntimeTool:
    name: str
    description: str
    input_schema: dict[
        str,
        Any,
    ]
    invoke: ToolInvoke

    source: str = "mcp"

    mcp_server: (
        str | None
    ) = None

    mcp_tool: (
        str | None
    ) = None


def adapt_mcp_tool(
    manager: MCPClientManager,
    server_name: str,
    tool: mcp_types.Tool,
    exposed_name: (
        str | None
    ) = None,
) -> RuntimeTool:
    runtime_name = (
        exposed_name
        or tool.name
    )

    async def invoke(
        arguments: dict[
            str,
            Any,
        ]
    ) -> dict[str, Any]:
        return await manager.call_tool(
            server_name=server_name,
            tool_name=tool.name,
            arguments=arguments,
        )

    return RuntimeTool(
        name=runtime_name,
        description=(
            tool.description
            or ""
        ),
        input_schema=(
            tool.inputSchema
        ),
        invoke=invoke,
        source="mcp",
        mcp_server=server_name,
        mcp_tool=tool.name,
    )
```

---

# 12. 自动发现 MCP Tools

```python
async def register_mcp_tools(
    registry,
    manager: MCPClientManager,
) -> None:
    tools = await manager.list_tools(
        "web"
    )

    for remote_tool in tools:
        runtime_tool = adapt_mcp_tool(
            manager=manager,
            server_name="web",
            tool=remote_tool,
        )

        registry.register(
            runtime_tool
        )
```

Backend 启动后即可自动发现：

```text
web_search
web_fetch
browser_retrieve
verify_web_evidence
```

---

# 13. FastAPI 生命周期接入

```python
from contextlib import (
    asynccontextmanager,
)

from fastapi import FastAPI

from app.gwy.tools.mcp.manager import (
    MCPClientManager,
)

from app.gwy.tools.mcp.schemas import (
    MCPServerConfig,
)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    manager = MCPClientManager(
        configs=[
            MCPServerConfig(
                name="web",
                url=settings.WEB_MCP_URL,
                timeout_seconds=60,
            )
        ]
    )

    await manager.start()

    await register_mcp_tools(
        registry=tool_registry,
        manager=manager,
    )

    app.state.mcp_manager = manager

    try:
        yield

    finally:
        await manager.close()


app = FastAPI(
    lifespan=lifespan
)
```

---

# 14. Backend 配置

```env
WEB_MCP_URL=http://web-mcp:8001/mcp
```

如果后续需要鉴权：

```python
MCPServerConfig(
    name="web",
    url=settings.WEB_MCP_URL,
    headers={
        "Authorization": (
            f"Bearer "
            f"{settings.WEB_MCP_TOKEN}"
        )
    },
)
```

---

# 15. MCP Server Dockerfile

文件：

```text
mcp_servers/web/Dockerfile
```

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install \
    --no-cache-dir \
    -r requirements.txt

RUN playwright install \
    --with-deps \
    chromium

COPY server.py .

ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8001

EXPOSE 8001

CMD ["python", "server.py"]
```

---

# 16. docker-compose 示例

```yaml
services:

  backend:
    build: ./backend

    environment:
      WEB_MCP_URL: >
        http://web-mcp:8001/mcp

    depends_on:
      - web-mcp
      - searxng

  web-mcp:
    build:
      context: ./mcp_servers/web

    environment:
      MCP_HOST: 0.0.0.0
      MCP_PORT: 8001
      SEARXNG_URL: >
        http://searxng:8080

    shm_size: "1gb"

    depends_on:
      - searxng

    ports:
      - "8001:8001"

  searxng:
    image: searxng/searxng
```

生产环境如果只有 Backend 访问 Web MCP：

> 可以不把 `8001` 暴露到宿主机，只在 Docker Network 内访问。

---

# 17. 本地测试 MCP Client

```python
import asyncio

from mcp import ClientSession

from mcp.client.streamable_http import (
    streamable_http_client,
)


async def main():
    async with streamable_http_client(
        "http://localhost:8001/mcp"
    ) as (
        read,
        write,
        _,
    ):

        async with ClientSession(
            read,
            write,
        ) as session:

            await session.initialize()

            tools = (
                await session.list_tools()
            )

            print(
                [
                    tool.name
                    for tool
                    in tools.tools
                ]
            )

            result = (
                await session.call_tool(
                    "web_search",
                    {
                        "query": (
                            "2026 国考 "
                            "报名人数"
                        )
                    },
                )
            )

            print(result)


asyncio.run(main())
```

---

# 18. 第一版 MCP Tools

建议只保留：

```text
web_search
web_fetch
browser_retrieve
verify_web_evidence
```

不要第一版就开放：

```text
browser_click
browser_fill
browser_press
browser_scroll
browser_execute_js
```

原因：

- Tool Schema 过多；
- Agent 更难选；
- Browser 行为更难控制；
- 更难评测；
- 更容易陷入多步循环。

---

# 19. 如果后续必须操作表单

如果某网站必须：

```text
选择年份
输入岗位代码
点击查询
```

建议增加更高层的 MCP Tool：

```text
browser_query_form
```

而不是直接给 Agent 全套原子 Browser 操作。

示例接口：

```python
@mcp.tool()
async def browser_query_form(
    url: str,
    fields: dict[str, str],
    submit_selector: str,
) -> dict:
    ...
```

甚至固定站点可以进一步封装：

```text
query_registration_statistics(
    year,
    position_code
)
```

这种 Tool 更稳定，也更容易控制。

---

# 20. MCP Server 安全要求

浏览器 / Fetch MCP 可以访问网络，必须考虑 SSRF。

至少限制：

```text
localhost
127.0.0.1
private IP
link-local IP
Docker internal services
Cloud metadata
```

代码层 URL 校验只能解决一部分问题。

生产环境建议：

```text
Web MCP Container
      ↓
Outbound Firewall / Proxy
      ↓
Public Internet Only
```

不要允许 Web MCP 容器访问：

```text
PostgreSQL
Redis
Milvus
Backend Admin API
169.254.169.254
```

---

# 21. Browser Context 隔离

推荐：

```text
Chromium Process
= 全 Server 复用

BrowserContext
= 每次请求新建
```

这样兼顾：

```text
性能
+
Cookie / Session 隔离
```

如果未来需要跨 Tool Call 保持 Session，再额外设计：

```text
browser_session_id
```

第一版不建议立即增加。

---

# 22. MCP Tool 输出不要无限增长

网页内容可能几十万字符。

因此必须限制：

```text
max_chars
MAX_FETCH_BYTES
```

推荐：

```text
默认 20k chars
最大 100k chars
```

不要让 MCP 直接把整页无限传给 Agent。

---

# 23. 推荐调用流程

正常静态网页：

```text
web_search
→ web_fetch
→ verify_web_evidence
```

动态网页：

```text
web_search
→ web_fetch 失败 / 内容不足
→ browser_retrieve
→ verify_web_evidence
```

---

# 24. 最终配置建议

Backend：

```env
WEB_MCP_URL=http://web-mcp:8001/mcp
```

Web MCP Server：

```env
MCP_HOST=0.0.0.0
MCP_PORT=8001

SEARXNG_URL=http://searxng:8080

WEB_HTTP_TIMEOUT=20
WEB_BROWSER_TIMEOUT_MS=30000
```

---

# 25. 最终职责边界

## MCP Client Manager

```text
Connect
Initialize
List Tools
Call Tool
Reconnect
Close
```

## MCP Tool Adapter

```text
MCP Tool
→ Runtime Tool
```

## MCP Server

```text
Search
Fetch
Browser Retrieval
Evidence Matching
```

## SearXNG

```text
搜索引擎聚合
```

## Playwright

```text
动态网页读取
```

---

# 26. 推荐改造顺序

```text
Phase 1
Web MCP Server

Phase 2
独立 MCP Client 测试

Phase 3
MCPClientManager

Phase 4
Tool Adapter

Phase 5
自动注册到现有 Tool Registry

Phase 6
Docker Compose 部署

Phase 7
SSRF / 网络安全加固
```

---

# 27. 最终目标结构

```text
GwyPilot Backend
        │
        ↓
MCP Client Manager
        │
        ↓
http://web-mcp:8001/mcp
        │
        ↓
GwyPilot Web MCP Server
        │
        ├── web_search
        ├── web_fetch
        ├── browser_retrieve
        └── verify_web_evidence
                │
         ┌──────┴──────┐
         ↓             ↓
      SearXNG       Playwright
                       ↓
                    Chromium
```

最终项目只需要维护一个统一的 Web MCP 远程能力入口：

```env
WEB_MCP_URL=http://web-mcp:8001/mcp
```

而 Agent Runtime 无需直接依赖：

```text
SearXNG SDK
httpx 抓取逻辑
Playwright Browser 生命周期
```

这样可以把 Web 能力从主应用中彻底解耦出来。
