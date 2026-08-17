# GwyPilot 公务员岗位智能分析平台

GwyPilot 是一个面向公务员岗位分析与政策问答场景的智能分析平台，围绕岗位筛选、政策检索、网页补证、风险审查、报告生成、复习规划和飞书推送，构建了一套可追踪、可回放、可评测的 Agent 工作流。

## 项目功能

### 1. 岗位智能分析

- 支持按专业、学历、学位、政治面貌、地区、部门等条件进行岗位筛选
- 岗位数据进入 PostgreSQL，适合做结构化过滤与精确判断
- 对候选岗位进行匹配分析、风险审查和结果汇总
- 输出岗位分析报告、推荐结论和可解释的判断依据

### 2. 政策问答与 Agentic RAG

- 政策公告、报考指南、专业目录等资料进入 Milvus 做向量检索
- 支持政策问答、报考条件核验、专业目录补证和相关规则解释
- 支持文本、语音、图片、PDF 等多模态输入
- 结合文档解析、OCR、多轮检索和上下文压缩，生成可引用的回答

### 3. Web 补证与证据核验

- 支持网页检索、页面抓取和网页证据核验
- 用于补足报录比、公告原文、政策细则和岗位来源信息
- 支持把网页证据纳入 trace，便于回放和排错

### 4. 复习规划与备考建议

- 根据用户背景、目标岗位和时间资源生成学习计划
- 支持短期复习安排、长期备考策略和阶段性任务拆解
- 可结合岗位分析结果和政策问答结果生成更贴近目标岗位的备考建议

### 5. 长短期记忆

- 支持会话内短期工作记忆
- 支持跨对话长期画像与偏好沉淀
- 通过 Redis 管理会话上下文压缩，并在必要时做 side-query 补充

### 6. 报告生成与结果输出

- 生成岗位分析报告、政策问答结果、复习规划和汇总性结论
- 支持飞书推送，方便把结果输出到外部协作工具
- 保留中间过程、引用证据和最终结论，便于复盘

### 7. Trace 与评测

- 记录任务规划、工具调用、检索结果、验证过程和最终输出
- 支持在线与离线评测
- 可对任务成功率、工具调用、证据质量、回答质量、效率等维度进行分析
- 方便做版本对比、回归测试和效果追踪

## 核心实现

### Agent Runtime

- 采用分层 Agent 架构构建主流程
- 主 Agent 使用 Plan-and-Execute 范式，负责任务拆解、调度和重规划
- 子 Agent 使用 ReAct 范式，按需调用工具完成局部任务
- 通过 `todo_write` / `todo_tasks` 维护任务拆解与执行状态
- 支持动态路由、异常重试、权限控制和结果回收

### Agentic RAG

- 将政策类知识统一接入检索链路
- 结合 Redis 做上下文压缩，降低长对话成本
- 结合 Milvus 做向量召回和知识检索
- 结合文档解析、OCR 和多模态摘要补足非结构化内容

### MCP 工具层

- 外部能力按 MCP Tool 风格封装
- 当前重点覆盖 Web、DB、Playwright 等工具能力
- 统一工具注册、调用和 trace 记录方式
- 便于后续继续接入更多检索和执行能力

### 权限与安全

- 对高风险工具做权限 gate
- 支持 allow、ask、review、deny 等分层控制
- 降低错误工具调用、越权调用和伪完成风险

## 技术栈

- 后端：Python、FastAPI、SQLModel、Pydantic、LangGraph
- Agent 体系：Agent Runtime、Plan-and-Execute、ReAct、Skills
- 数据库：PostgreSQL
- 缓存：Redis
- 向量检索：Milvus
- 前端：React、TypeScript、Vite
- 工具层：MCP
- 文档处理：OCR、PDF 解析、多模态摘要、文本抽取
- 测试：Pytest、Playwright

## 目录说明

```text
backend/
  app/gwy/            GwyPilot 业务代码
  app/api/            FastAPI 路由
  tests/              后端测试
frontend/             React 前端
docs/                 设计文档、实现记录和整理说明
scripts/              本地开发和测试脚本
```

## 设计原则

- 结构化筛选优先，岗位判断依赖 PostgreSQL，不用 RAG 代替结构化过滤
- 可解释，输出尽量带依据、理由和风险说明
- 可追踪，保留关键步骤、证据来源和中间结果
- 可扩展，工具层按统一风格封装，便于后续接更多能力

## 快速开始

### 后端

```bash
cd backend
pip install -e .
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
```

### 前端

```bash
bun install
bun run --filter frontend dev -- --host 0.0.0.0 --port 5173
```

## 常用命令

### 后端

```bash
cd backend
bash ./scripts/test.sh
bash ./scripts/lint.sh
bash ./scripts/format.sh
```

### 前端

```bash
bun run --filter frontend lint
bun run --filter frontend test
```

## 文档入口

更细的设计说明和实现记录放在 [`docs/README.md`](docs/README.md)。

## 说明

这个项目主要面向公务员考试相关的岗位分析与备考辅助场景，当前阶段聚焦 MVP 能力，不做自动报名、刷题系统、申论批改、面试陪练等功能。
