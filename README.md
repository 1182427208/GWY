# GwyPilot

公务员岗位决策与备考辅助平台，基于 `fastapi/full-stack-fastapi-template` 二次开发。

项目目标是把结构化岗位筛选、政策知识检索、网页补证、风险提示、报告生成和学习计划串成一条可追踪的 Agent 工作流，帮助用户更快完成岗位判断和备考规划。

## 当前能力

- 结构化岗位库导入与筛选：岗位表进入 PostgreSQL，按专业、学历、学位、政治面貌、地区等条件做精确过滤
- 政策与指南检索：政策公告、报考指南、专业目录进入 Milvus，供 Agentic RAG 检索
- 岗位分析工作流：基于 LangGraph 串联岗位事实、政策证据、网页补证、风险审查和报告生成
- 复习规划：根据用户背景、目标岗位和时间资源生成学习计划
- 记忆系统：支持短期工作记忆和跨对话长期画像
- 飞书推送：支持将分析报告或计划推送到飞书
- 可追踪输出：保留分析轨迹、引用证据和中间结果

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端 | FastAPI, SQLModel, Pydantic, LangGraph |
| 结构化数据 | PostgreSQL |
| 向量检索 | Milvus |
| 缓存 | Redis |
| Web 检索 | SearXNG, Fetch MCP, Playwright MCP |
| 文档处理 | PyMuPDF, pandas, openpyxl, OCR / multimodal summary |
| 前端 | React, TypeScript, Vite |
| 测试 | Pytest, Playwright |

## 环境要求

- Python `3.10`
- Node.js `20+`
- Bun `1.x`
- Docker Desktop / Docker Compose
- PostgreSQL、Redis、Milvus 可通过 Docker 启动

后端版本约束来自 [`backend/pyproject.toml`](./backend/pyproject.toml)，当前声明为 `>=3.10,<4.0`，Docker 镜像也基于 `python:3.10`。

## 目录说明

```text
backend/app/
├── api/routes/               API 路由
├── gwy/
│   ├── agents/               LangGraph Agent 编排
│   ├── document/             PDF / 图片 / 表格解析
│   ├── llm/                  模型调用封装
│   ├── mcp_tools/            MCP Tool 风格工具层
│   ├── prompts/              Prompt 模板
│   ├── services/             业务服务
│   ├── skills/               稳定规则与轻量推理
│   └── vectorstores/         Milvus 适配
frontend/                     React 前端
docker/milvus/                Milvus 本地独立启动配置
docs/                         方案、计划和补充文档
```

## 快速开始

### 1. 安装依赖

前端：

```bash
npm install
```

后端：

```bash
cd backend
pip install -e .
```

如果你平时用 `uv`，也可以在后端目录执行：

```bash
uv sync
```

### 2. 准备环境变量

复制根目录 `.env.example` 为 `.env`，至少确认这些配置：

- `POSTGRES_SERVER`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `REDIS_URL`
- `MILVUS_URI`
- `SILICONFLOW_API_KEY` 或 `LLM_API_KEY`

### 3. 启动依赖服务

如果你本地单独跑 Milvus：

```powershell
cd docker/milvus
docker compose up -d
```

如果你只想看日志：

```powershell
docker compose logs -f
```

PostgreSQL / Redis 可以按模板默认 Docker 方式启动，或者使用你自己的本地服务。

### 4. 启动后端

```powershell
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
```

### 5. 启动前端

在项目根目录执行：

```powershell
npm run dev -- --host 0.0.0.0 --port 5173
```

## 访问地址

- 前端：`http://localhost:5173`
- 后端 API：`http://localhost:8000`
- Swagger：`http://localhost:8000/docs`
- Milvus：`http://localhost:19530`

如果你使用模板里的完整 Docker 部署方式，还会额外用到：

- Adminer：`http://localhost:8080`
- Traefik 面板：`http://localhost:8090`

## 常用命令

后端测试：

```bash
cd backend
bash ./scripts/test.sh
```

后端 lint：

```bash
cd backend
bash ./scripts/lint.sh
```

后端格式化：

```bash
cd backend
bash ./scripts/format.sh
```

前端 lint：

```bash
bun run --filter frontend lint
```

前端测试：

```bash
bun run --filter frontend test
```

## 当前实现边界

- 已实现：岗位筛选、政策检索、岗位分析、网页补证、学习计划、短长期记忆、飞书推送
- 部分实现：图片 OCR / 多模态摘要能力已接入，但扫描类 PDF 和复杂版式仍有增强空间
- 当前不做：自动报名、刷题系统、申论批改、面试陪练、MiniMind 微调

## 设计原则

- 结构化优先：岗位筛选依赖 PostgreSQL，不用 RAG 替代结构化过滤
- 可解释：输出尽量带依据、理由和风险说明
- 可追踪：保留 LangGraph 工作流中的关键步骤和证据来源
- 可扩展：工具层按 MCP Tool 风格封装，便于后续接更多检索与执行能力

## 说明

这个仓库是在 `fastapi/full-stack-fastapi-template` 基础上演化出来的公务员岗位分析项目，不再是模板原样使用。模板历史已经剥离，当前仓库以 GwyPilot 自身功能为主。
