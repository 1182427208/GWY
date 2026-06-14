# GwyPilot — 公务员岗位决策与备考工作流 Agent

基于 [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) 二次开发。

> 根据用户画像、职位表、专业目录、报考指南等数据，自动筛选适合岗位，解释匹配原因，标记风险，生成推荐报告和学习计划，并推送到飞书。

## 核心能力

```text
结构化职位库 + 规则引擎 + Agentic RAG + 风险审查 + 记忆系统 + 飞书推送 + Agent Trace
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Pydantic + SQLModel |
| 数据库 | PostgreSQL（职位表） |
| 向量库 | Milvus（政策、指南、专业目录） |
| 缓存 | Redis |
| Agent 编排 | LangGraph |
| 前端 | React + TypeScript + Vite + Tailwind CSS + shadcn/ui |
| 测试 | Pytest |
| 部署 | Docker Compose + Traefik |

## 项目结构

```
backend/app/
├── gwy/                    # GwyPilot 核心模块
│   ├── agents/             # Agent 实现（岗位决策、政策证据、风险审查、报告生成、飞书推送等）
│   ├── document/           # 文档导入与解析
│   ├── document_processing/ # 文档处理流水线
│   ├── evals/              # 评测与质量保障
│   ├── llm/                # LLM 调用封装
│   ├── mcp_tools/          # MCP Tool 风格工具层
│   ├── prompts/            # Prompt 模板
│   ├── services/           # 业务服务层
│   ├── skills/             # Agent 技能模块
│   └── vectorstores/       # 向量库适配（Milvus）
├── api/routes/
│   ├── gwy.py              # GwyPilot API 路由
│   └── gwy_analysis.py     # 岗位分析 API
└── ...
frontend/                   # React 前端（当前阶段不新增页面）
```

## 快速开始

### 环境要求

- Docker & Docker Compose
- Python 3.12+
- Node.js 20+ / Bun

### 启动开发环境

```bash
# 启动全部服务（PostgreSQL、Milvus、Redis、后端、前端）
docker compose watch

# 或单独启动前后端
npm run dev -- --host 0.0.0.0 --port 5173
```

启动后访问：

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| 后端 API | http://localhost:8000 |
| Swagger 文档 | http://localhost:8000/docs |
| Adminer（数据库管理） | http://localhost:8080 |
| Traefik 面板 | http://localhost:8090 |

### 环境变量

复制 `.env.example` 为 `.env`，按需修改配置。主要变量：

- `DOMAIN` — 部署域名（本地为 localhost）
- `ENVIRONMENT` — 运行环境：`local` / `staging` / `production`
- `FRONTEND_HOST` — 前端地址

## 测试

```bash
# 后端测试
cd backend && bash ./scripts/test.sh

# 后端 Lint
cd backend && bash ./scripts/lint.sh

# 后端格式化
cd backend && bash ./scripts/format.sh

# 前端 Lint
bun run --filter frontend lint

# 前端测试
bun run --filter frontend test
```

## MVP 功能（第一阶段）

- [x] 结构化岗位库导入（国考 / 省考 Excel）
- [x] 政策文档、报考指南、专业目录导入
- [x] Agentic RAG 知识检索（Milvus）
- [x] 岗位匹配与决策 Agent
- [x] 推荐报告生成
- [x] 风险审查
- [x] Agent Trace / 评测
- [x] 飞书推送通知

## 设计原则

- **可解释**：每个推荐附带匹配原因与证据来源
- **可追踪**：Agent 决策链完整记录
- **可回放**：相同输入可复现相同结果
- **结构化优先**：职位筛选走 PostgreSQL，RAG 只做知识检索

## 许可

本项目基于 [FastAPI Full Stack Template](https://github.com/fastapi/full-stack-fastapi-template) 构建，遵循其原有许可协议。

## 致谢

- [FastAPI](https://fastapi.tiangolo.com)
- [full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)
- [LangGraph](https://langchain.com/langgraph)
- [Milvus](https://milvus.io)
