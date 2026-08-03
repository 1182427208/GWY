# GwyPilot Backend Modules

本目录是在 `fastapi/full-stack-fastapi-template` 基础上的扩展层，保留模板原有结构，不重构已有用户、认证、Docker 和测试体系。

## 目录职责
- `agents/`
  - LangGraph Agent 编排入口
- `skills/`
  - 可复用的规则、意图路由、轻量推理逻辑
- `mcp_tools/`
  - 按 MCP Tool 风格封装的工具层
- `services/`
  - 业务服务层，负责导入、检索、会话、缓存、调试
- `document/`
  - PDF 解析、版面分析、图片/表格抽取、切分、资产关联
- `llm/`
  - SiliconFlow OpenAI-compatible 模型封装
- `vectorstores/`
  - Milvus 读写封装
- `evals/`
  - 轻量评测、回归测试和验收脚本
- `prompts/`
  - Prompt 模板与系统提示词

## 约定
- 后端新增代码优先放在 `backend/app/gwy/`
- 职位表进入 PostgreSQL，不能用 RAG 替代结构化筛选
- 政策、报考指南、专业目录进入 Milvus，供 Agentic RAG 使用
- 主流程使用 LangGraph，工具层按 MCP Tool 风格封装，不直接在 Agent 中散落 function call
- 第一阶段只做 MVP，不做自动报名、刷题、申论批改、面试陪练、MiniMind 微调

## Search Query Planner
- 入口：`app.gwy.services.search_query_planner_service.SearchQueryPlannerService.plan`。
- 输入：`SearchQueryRequest` 的 `query`、`search_kind`、可选 `position`、已有 `planned_queries` 和 `max_queries`。
- 输出：`SearchQueryPlan`，包含 `primary_query`、`planned_queries`、`required_source_kinds`、`search_kind` 和可回放的 `trace`。
- Planner 使用 `ChatService` 生成 JSON 查询候选；模型输出不可解析或不可用时，自动回退到确定性规则，不中断调用。

## Web Retrieval 约定
- `SearXNG` 负责搜索，默认通过 `SEARXNG_BASE_URL` 配置。
- `Fetch MCP` 负责读取网页正文，配置 `FETCH_MCP_URL` 后优先走外部服务；未配置时回退到本地 HTTP 抓取。
- `Playwright MCP` 负责动态页面读取，配置 `PLAYWRIGHT_MCP_URL` 后启用；未配置时仅在网页抓取不足时跳过。
- `WEB_MCP_URL` 是当前统一 Web MCP 主入口，优先承载 `web_search`、`web_fetch`、`browser_retrieve`、`verify_web_evidence`。
- `DB_MCP_URL` 是只读数据库 MCP 主入口，提供表结构和数据查询能力，默认通过 `streamable-http` 的 `/mcp` 路径访问。
- PDF 解析保持本地实现，继续复用 `document/` 下的解析、切分、表格抽取能力。

### 本地 Playwright MCP 启动
- 启动本地服务：`python -m app.gwy.mcp_tools.playwright_server`
- 客户端配置：`PLAYWRIGHT_MCP_URL=http://localhost:8931/mcp`
- 当前服务默认监听 `127.0.0.1:8931`，同时提供 `streamable-http` 的 `/mcp` 路径和兼容的 `/sse` 路径。
- 适用场景：当网页正文抓取不足、页面需要执行脚本渲染、或需要补齐报录比、进面分数、公告原文等动态内容时，优先走本地 Playwright MCP。

## MCP 工具总览

当前项目里对外提供或使用到的 MCP 入口有三类：

- `gwy-web`
  - 统一 Web MCP server
  - 协议：Model Context Protocol + Streamable HTTP
- `gwy-db`
  - 只读数据库 MCP server
  - 协议：Model Context Protocol + Streamable HTTP
- `gwy-playwright`
  - 兼容性的独立 Playwright MCP server
  - 协议：Model Context Protocol + Streamable HTTP
  - 同时保留 `/sse`

这些工具会通过 `app.gwy.agent_runtime.builtin_tools.register_builtin_tools()` 自动注册到 agent runtime 的 `ToolRegistry`，agent 可以直接按工具名调用。
默认情况下，后端启动时会先拉起本地 Web / DB / Playwright MCP，再启动 FastAPI 服务；如果你显式配置了对应的 `*_MCP_URL`，就会优先连接外部 MCP 而不会再起本地实例。

### Web MCP

文件：
- [backend/app/gwy/mcp_tools/web_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/web_server.py)

工具：
- `web_search`
- `web_fetch`
- `browser_retrieve`
- `verify_web_evidence`

输入和输出：
- `web_search(query: str, max_results: int = 5) -> dict`
  - 输入：检索词、最多返回条数
  - 输出：`query`、`count`、`results`
  - `results` 的每项通常包含 `title`、`url`、`snippet`、`source`
- `web_fetch(url: str, max_chars: int = 20000) -> dict`
  - 输入：网页 URL、截断字符数
  - 输出：`url`、`final_url`、`title`、`text`、`content_type`、`status_code`、`source`、`retrieved_via`、`is_pdf`、`text_length`
- `browser_retrieve(url: str, selector: str = "body", wait_ms: int = 800, max_chars: int = 20000) -> dict`
  - 输入：网页 URL、CSS 选择器、等待毫秒数、截断字符数
  - 输出字段和 `web_fetch` 类似，但 `retrieved_via` 通常是 `web_mcp:browser_retrieve`
- `verify_web_evidence(query: str, planned_queries: list[str] | None = None, top_k: int = 3, seed_urls: list[str] | None = None) -> dict`
  - 输入：主查询、预设查询、检索深度、种子 URL
  - 输出：`evidence`、`failures`、`trace`、`attempts`、`insufficient_evidence`

### DB MCP

文件：
- [backend/app/gwy/mcp_tools/db_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/db_server.py)

工具：
- `list_tables`
- `describe_table`
- `sample_rows`
- `query_sql`

输入和输出：
- `list_tables() -> dict`
  - 输出：`tables`、`count`、`schema_count`
- `describe_table(table_name: str) -> dict`
  - 输入：表名
  - 输出：`table_name`、`columns`、`column_count`、`primary_key_columns`
- `sample_rows(table_name: str, limit: int = 5) -> dict`
  - 输入：表名、采样行数
  - 输出：`table_name`、`limit`、`row_count`、`rows`
- `query_sql(sql: str, limit: int = 50) -> dict`
  - 输入：只读 SQL、最大返回行数
  - 输出：`sql`、`limit`、`row_count`、`columns`、`rows`

安全约束：
- 只允许单条 `SELECT` 或 `WITH` 查询
- 显式拒绝 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`TRUNCATE`
- 不允许多语句

### 兼容 Playwright MCP

文件：
- [backend/app/gwy/mcp_tools/playwright_server.py](/E:/GwyPilot/GwyPilot/backend/app/gwy/mcp_tools/playwright_server.py)

工具：
- `read_page(url: str, timeout_seconds: float = 20.0) -> dict`

返回：
- 成功时：`ok=True`、`url`、`final_url`、`title`、`text`、`content_type`、`source`、`retrieved_via`、`text_length`
- 失败时：`ok=False`、`url`、`error`

## 调用方式

项目内推荐优先使用封装好的客户端或服务：

- Web：`app.gwy.services.web_mcp_client.WebMCPClient`
- DB：`app.gwy.services.db_mcp_client.DatabaseMCPClient`
- 浏览器读取：`app.gwy.services.playwright_mcp_service.PlaywrightMCPService`

直接用 MCP 协议调用时，使用 `mcp.ClientSession` + `mcp.client.streamable_http.streamable_http_client`：

```python
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with streamable_http_client("http://localhost:8001/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "web_search",
                {"query": "中央办公厅 报录比", "max_results": 5},
            )
            print(result)


asyncio.run(main())
```

## 建议的调用顺序
- Web 证据检索：`web_search` → `web_fetch` → `browser_retrieve` → `verify_web_evidence`
- 数据库检查：`list_tables` → `describe_table` → `sample_rows` → `query_sql`
- 动态网页兜底：优先统一 Web MCP，必要时再走独立 Playwright MCP
