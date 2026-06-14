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

## Web Retrieval 约定
- `SearXNG` 负责搜索，默认通过 `SEARXNG_BASE_URL` 配置。
- `Fetch MCP` 负责读取网页正文，配置 `FETCH_MCP_URL` 后优先走外部服务；未配置时回退到本地 HTTP 抓取。
- `Playwright MCP` 负责动态页面读取，配置 `PLAYWRIGHT_MCP_URL` 后启用；未配置时仅在网页抓取不足时跳过。
- PDF 解析保持本地实现，继续复用 `document/` 下的解析、切分、表格抽取能力。

## 约定
- 后端新增代码优先放在 `backend/app/gwy/`
- 职位表进入 PostgreSQL，不能用 RAG 替代结构化筛选
- 政策、报考指南、专业目录进入 Milvus，供 Agentic RAG 使用
- 主流程使用 LangGraph，工具层按 MCP Tool 风格封装，不直接在 Agent 中散落 function call
- 第一阶段只做 MVP，不做自动报名、刷题、申论批改、面试陪练、MiniMind 微调
