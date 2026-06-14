# GwyPilot 项目说明

## 项目目标
- 基于 `fastapi/full-stack-fastapi-template` 二次开发，保留模板原有结构，不重构运行方式。
- 面向公务员考试岗位推荐与备考辅助，第一阶段只做 MVP：结构化岗位库、政策 RAG、检索、trace 和基础导入。

## 技术栈
- 后端：FastAPI、SQLModel、PostgreSQL、Pydantic、LangGraph、Redis。
- 向量库：Milvus。
- 前端：React + TypeScript + Vite，当前阶段不新增页面。
- 测试：Pytest。

## 目录约定
- 后端新增代码优先放在 `backend/app/gwy/`。
- 模板已有目录保持原样，只做必要扩展，不移动既有结构。
- 职位表必须进入 PostgreSQL，政策、报考指南、专业目录进入 Milvus 做 Agentic RAG。
- 主流程使用 LangGraph，工具层按 MCP Tool 风格封装，不直接把 function call 作为主设计。

## 核心原则
- 保持可解释、可追踪、可回放。
- 先做可测试的最小实现，再逐步扩展 Agent 能力。
- 结构化筛选依赖 PostgreSQL，RAG 只负责知识检索，不替代岗位过滤。

## 禁止事项
- 不要重构 `full-stack-fastapi-template` 的原有骨架。
- 不做自动报名、刷题系统、申论批改、面试陪练、MiniMind 微调。
- 不做前端页面新增。
- 不用 RAG 替代岗位表的结构化筛选。

## 测试命令
- 后端测试：`cd backend && bash ./scripts/test.sh`
- 后端 lint：`cd backend && bash ./scripts/lint.sh`
- 后端格式化：`cd backend && bash ./scripts/format.sh`
- 前端 lint：`bun run --filter frontend lint`
- 前端测试：`bun run --filter frontend test`
