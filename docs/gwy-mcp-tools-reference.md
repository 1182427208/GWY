# GwyPilot MCP 工具参考

本文档只记录当前项目中已经落地、可以直接调用的 MCP 入口与工具契约。

## 1. 当前 MCP 服务器

### 1.1 `gwy-web`

- 文件：[backend/app/gwy/mcp_tools/web_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/web_server.py)
- 协议：Model Context Protocol over Streamable HTTP
- 默认地址：`http://127.0.0.1:8001/mcp`
- 职责：统一承载网页搜索、网页抓取、浏览器读取、网页证据核验

### 1.2 `gwy-db`

- 文件：[backend/app/gwy/mcp_tools/db_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/db_server.py)
- 协议：Model Context Protocol over Streamable HTTP
- 默认地址：`http://127.0.0.1:8002/mcp`
- 职责：只读数据库结构查看与数据抽样、查询

### 1.3 `gwy-playwright`

- 文件：[backend/app/gwy/mcp_tools/playwright_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/playwright_server.py)
- 协议：Model Context Protocol over Streamable HTTP
- 默认地址：`http://127.0.0.1:8931/mcp`
- 兼容路径：同时保留 `/sse`
- 职责：独立的浏览器页面读取兼容入口，主要用于网页正文不足时的兜底

## 2. Web MCP 工具

### 2.1 `web_search`

- 位置：[backend/app/gwy/mcp_tools/web_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/web_server.py)
- 入参：
  - `query: str`
  - `max_results: int = 5`
- 出参：
  - `query`
  - `count`
  - `results: list[dict]`
- `results` 常见字段：
  - `title`
  - `url`
  - `snippet`
  - `source`

### 2.2 `web_fetch`

- 位置：[backend/app/gwy/mcp_tools/web_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/web_server.py)
- 入参：
  - `url: str`
  - `max_chars: int = 20000`
- 出参：
  - `url`
  - `final_url`
  - `title`
  - `text`
  - `content_type`
  - `status_code`
  - `source`
  - `retrieved_via`
  - `is_pdf`
  - `text_length`

### 2.3 `browser_retrieve`

- 位置：[backend/app/gwy/mcp_tools/web_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/web_server.py)
- 入参：
  - `url: str`
  - `selector: str = "body"`
  - `wait_ms: int = 800`
  - `max_chars: int = 20000`
- 出参：
  - 同 `web_fetch` 的返回结构
  - `retrieved_via` 通常为 `web_mcp:browser_retrieve`

### 2.4 `verify_web_evidence`

- 位置：[backend/app/gwy/mcp_tools/web_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/web_server.py)
- 入参：
  - `query: str`
  - `planned_queries: list[str] | None = None`
  - `top_k: int = 3`
  - `seed_urls: list[str] | None = None`
- 出参：
  - `evidence`
  - `failures`
  - `trace`
  - `attempts`
  - `insufficient_evidence`

## 3. DB MCP 工具

### 3.1 `list_tables`

- 位置：[backend/app/gwy/mcp_tools/db_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/db_server.py)
- 入参：无
- 出参：
  - `tables`
  - `count`
  - `schema_count`

### 3.2 `describe_table`

- 位置：[backend/app/gwy/mcp_tools/db_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/db_server.py)
- 入参：
  - `table_name: str`
- 出参：
  - `table_name`
  - `columns`
  - `column_count`
  - `primary_key_columns`

### 3.3 `sample_rows`

- 位置：[backend/app/gwy/mcp_tools/db_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/db_server.py)
- 入参：
  - `table_name: str`
  - `limit: int = 5`
- 出参：
  - `table_name`
  - `limit`
  - `row_count`
  - `rows`

### 3.4 `query_sql`

- 位置：[backend/app/gwy/mcp_tools/db_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/db_server.py)
- 入参：
  - `sql: str`
  - `limit: int = 50`
- 出参：
  - `sql`
  - `limit`
  - `row_count`
  - `columns`
  - `rows`

### 3.5 安全限制

- 仅允许单条 `SELECT` 或 `WITH` 语句
- 拒绝 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`TRUNCATE`
- 拒绝多语句输入
- 适合结构查看、抽样、只读分析，不适合写操作

## 4. 兼容 Playwright MCP 工具

### `read_page`

- 位置：[backend/app/gwy/mcp_tools/playwright_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/playwright_server.py)
- 入参：
  - `url: str`
  - `timeout_seconds: float = 20.0`
- 出参：
  - 成功时：`ok=True`、`url`、`final_url`、`title`、`text`、`content_type`、`source`、`retrieved_via`、`text_length`
  - 失败时：`ok=False`、`url`、`error`

## 5. 客户端与调用方式

### 5.1 项目内封装客户端

- Web 客户端：[backend/app/gwy/services/web_mcp_client.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/services/web_mcp_client.py)
- DB 客户端：[backend/app/gwy/services/db_mcp_client.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/services/db_mcp_client.py)
- 浏览器读取服务：[backend/app/gwy/services/playwright_mcp_service.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/services/playwright_mcp_service.py)

### 5.2 直接用 MCP 协议调用

```python
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with streamable_http_client("http://127.0.0.1:8001/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "web_search",
                {"query": "中央办公厅 报录比", "max_results": 5},
            )
            print(result)


asyncio.run(main())
```

## 6. 推荐调用顺序

- 网页证据链：`web_search` -> `web_fetch` -> `browser_retrieve` -> `verify_web_evidence`
- 数据库检查链：`list_tables` -> `describe_table` -> `sample_rows` -> `query_sql`
- 动态网页优先统一 Web MCP，只有网页正文不足时再考虑独立 Playwright 兼容入口

