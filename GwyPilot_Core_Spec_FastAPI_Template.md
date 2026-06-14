# GwyPilot 核心实现说明（基于 full-stack-fastapi-template 二次开发）

> 目标：让 Codex 基于 `https://github.com/fastapi/full-stack-fastapi-template` 快速二次开发，不读长文档也能抓住重点。  
> 本项目只做核心链路：**公考职位决策 Agent + Agentic RAG + 记忆 + 飞书推送 + Trace/评测**。

---

## 0. 基础项目说明

基于 `fastapi/full-stack-fastapi-template` 二次开发。保留模板已有能力：

- 后端：FastAPI + SQLModel + PostgreSQL + Pydantic
- 前端：React + TypeScript + Vite
- 部署：Docker Compose
- 权限：JWT 登录、用户系统
- 测试：Pytest
- 前后端自动生成 client

不要重写模板结构，只在原有 `backend/app` 和 `frontend/src` 上扩展。

---

## 1. 项目定位

项目名：**GwyPilot：公考职位决策与备考工作流 Agent**

一句话：

> 根据用户画像、职位表、专业目录、报考指南、进面分数线等数据，自动筛选适合岗位，解释匹配原因，标记风险，生成推荐报告和学习计划，并推送到飞书。

不要做成普通问答系统。核心是：

```text
结构化职位库
  + 规则引擎
  + Agentic RAG
  + 风险审查
  + 记忆系统
  + 飞书推送
  + Agent Trace
```

---

## 2. MVP 必做功能

第一版只做 8 个核心功能。

### 2.1 职位表导入

支持管理员上传国考/省考 Excel 职位表，解析并写入 PostgreSQL。

核心字段：

```text
year
exam_type
province
department_name
agency_name
position_name
position_code
description
recruit_count
education_requirement
degree_requirement
major_requirement
political_status_requirement
grassroots_years_requirement
fresh_graduate_requirement
work_location
household_requirement
certificate_requirement
remark
consult_phone
source_file
```

注意：

- 职位表是结构化数据，必须进 PostgreSQL。
- 不要把职位表直接丢进向量库做 RAG。
- 字段名不同的 Excel 要做字段映射。

---

### 2.2 政策文档导入

支持导入：

```text
招考公告
报考指南
考试大纲
专业目录
```

处理方式：

```text
PDF / Markdown / TXT
  ↓
按条款切分
  ↓
embedding
  ↓
写入 Milvus
```

metadata 必须包含：

```text
year
exam_type
province
doc_type
doc_title
section
source_file
```

---

### 2.3 用户画像

用户填写或自然语言抽取：

```text
学历
学位
研究生专业
本科专业
政治面貌
是否应届
基层经历
目标地区
岗位偏好
不接受条件
每日学习时间
```

存入 PostgreSQL。

---

### 2.4 岗位推荐主流程

输入：

```json
{
  "user_id": "xxx",
  "exam_year": 2026,
  "exam_type": "national",
  "target_regions": ["河南", "四川"],
  "top_k": 10
}
```

输出：

```text
筛选概览
Top 10 岗位
每个岗位的匹配原因
每个岗位的风险提示
专业匹配是否需人工确认
竞争风险
政策依据
```

---

### 2.5 风险审查

识别以下风险：

```text
专业不确定
最低服务年限
经常出差
经常加班/值班
艰苦边远地区
户籍限制
证书要求
基层执法
招录人数少
竞争风险高
```

输出必须结构化：

```json
{
  "risk_level": "low | medium | high",
  "risk_items": [
    {
      "risk_type": "service_year_limit",
      "evidence": "备注中提到最低服务年限5年",
      "explanation": "录用后短期流动性较低",
      "suggestion": "如计划继续深造或跨地区发展，需谨慎选择"
    }
  ]
}
```

---

### 2.6 Agentic RAG 政策问答

支持问题：

```text
应届生身份怎么认定？
基层工作经历怎么算？
专业不完全一致怎么办？
资格复审要准备什么？
公共科目考什么？
```

要求：

- 必须带引用。
- 找不到依据就回答不确定。
- 不能编造政策。
- 如果年份不匹配，要提示“历史数据，仅供参考”。

---

### 2.7 飞书推送

MVP 只做飞书自定义机器人 Webhook。

推送内容：

```text
岗位推荐报告
风险提示
每日学习计划
周复盘，后续
```

---

### 2.8 Agent Trace

每次岗位推荐任务保存 trace：

```text
节点执行状态
工具调用记录
检索 query
引用片段
Reflection / Guard 检查结果
耗时
错误
```

用于前端展示和后续评测。

---

## 3. Agent 设计：只保留核心 Agent

不要第一版做太多 Agent。只做下面 7 个。

### 3.1 PositionDecisionAgent

主 Agent，用 LangGraph 编排。

策略：

```text
固定 LangGraph 流程
+ Plan-and-Execute 思想
+ 部分节点 Reflection
```

流程：

```text
MemoryRetrievalNode
  ↓
PositionQueryNode
  ↓
HardRuleFilterNode
  ↓
MajorMatchAgent
  ↓
PolicyRAGAgent
  ↓
RiskReviewAgent
  ↓
CompetitionAnalysisNode
  ↓
RankingNode
  ↓
GuardrailNode
  ↓
ReportGeneratorNode
  ↓
FeishuPushNode
  ↓
MemoryConsolidationNode
```

不要让大模型自由规划整个流程。主流程固定，保证可控。

---

### 3.2 HardRuleFilterNode

策略：

```text
Rule Engine
```

不用 LLM。

判断：

```text
学历
学位
政治面貌
基层经历
应届身份
地区
户籍
证书
```

输出：

```json
{
  "passed": true,
  "failed_reasons": [],
  "rule_trace": []
}
```

---

### 3.3 MajorMatchAgent

策略：

```text
规则匹配
+ 专业目录 RAG
+ ReAct 子流程
+ Reflection
```

执行：

```text
1. 字符串精确匹配
2. 专业大类匹配
3. 不确定时检索专业目录
4. 仍不确定则标记 need_manual_confirm=true
5. Reflection 检查是否把不确定说成确定
```

输出：

```json
{
  "match_type": "exact | category | related | uncertain | not_match",
  "confidence": 0.78,
  "need_manual_confirm": true,
  "reason": "...",
  "evidence": []
}
```

---

### 3.4 PolicyRAGAgent

策略：

```text
Agentic RAG
+ Query Rewrite
+ Hybrid Search
+ Rerank
+ Citation Guard
```

流程：

```text
用户问题/内部检索需求
  ↓
Query Rewrite
  ↓
Milvus 向量检索
  ↓
BM25，可选
  ↓
Rerank
  ↓
生成带引用回答
  ↓
Citation Guard
```

输出：

```json
{
  "answer": "...",
  "citations": [
    {
      "doc_title": "...",
      "section": "...",
      "content": "..."
    }
  ],
  "confidence": 0.82,
  "need_manual_confirm": false
}
```

---

### 3.5 RiskReviewAgent

策略：

```text
关键词规则
+ LLM 结构化抽取
+ ReAct 工具调用
+ Reflection
```

执行：

```text
1. 先用关键词识别明显风险
2. LLM 抽取备注中的隐含风险
3. 如涉及政策，调用 PolicyRAGAgent
4. 如涉及专业，读取 MajorMatchAgent 结果
5. 结合用户 avoid_conditions 计算风险等级
6. Reflection 检查是否遗漏用户不接受条件
```

---

### 3.6 RankingAgent

策略：

```text
规则打分
+ LLM 只负责解释
```

评分建议：

```text
总分 =
硬条件分
+ 专业匹配分
+ 地区偏好分
+ 岗位方向匹配分
+ 招录人数分
+ 历史分数友好度
- 风险扣分
- 竞争风险扣分
- 用户排除偏好扣分
```

不要让 LLM 直接排序。

---

### 3.7 ReportGeneratorAgent

策略：

```text
模板生成
+ LLM 润色
+ Reflection
```

输出 Markdown：

```text
岗位推荐概览
Top 10 岗位
每个岗位匹配理由
风险提示
政策依据
备考建议
```

报告生成后必须过 GuardrailNode。

---

## 4. MCP 设计：不用 function call

所有工具统一封装为 MCP Tool。Codex 实现时可以先写成本地 Python service，但接口和命名按 MCP 思路设计。

核心 MCP：

```text
position_query_mcp
rule_filter_mcp
major_catalog_search_mcp
policy_search_mcp
risk_extract_mcp
competition_query_mcp
ranking_mcp
memory_read_mcp
memory_write_mcp
trace_log_mcp
feishu_push_mcp
```

### MCP 工具层目录

放到：

```text
backend/app/gwy/mcp_tools/
```

示例：

```text
backend/app/gwy/mcp_tools/position_tools.py
backend/app/gwy/mcp_tools/policy_tools.py
backend/app/gwy/mcp_tools/risk_tools.py
backend/app/gwy/mcp_tools/memory_tools.py
backend/app/gwy/mcp_tools/feishu_tools.py
```

---

## 5. Skills 设计：只保留核心 Skills

Skills 是可复用能力，不是 Agent。

放到：

```text
backend/app/gwy/skills/
```

核心 Skills：

```text
excel_position_parse_skill
position_schema_mapping_skill
hard_condition_filter_skill
major_match_reasoning_skill
policy_query_rewrite_skill
policy_citation_guard_skill
remark_risk_extraction_skill
risk_level_scoring_skill
position_ranking_skill
recommendation_report_skill
feishu_card_generation_skill
trace_summary_skill
```

第一版不要写太多 Skills，以上够用。

---

## 6. Agent Memory：简化版长短期记忆

不要只做用户画像记忆。要做 Agent 长短期记忆，但 MVP 简化为 4 类。

### 6.1 Working Memory

位置：

```text
LangGraph State + Redis
```

存：

```text
当前任务目标
当前执行节点
候选岗位
中间结果
工具输出
错误
open questions
```

用途：

```text
节点间传递状态
失败恢复
trace 展示
```

---

### 6.2 Conversation Memory

位置：

```text
Redis，设置 TTL
```

存：

```text
当前会话正在讨论哪个岗位
上一轮用户意图
用户临时偏好
刚才对比的岗位
```

用途：

```text
理解“这个岗位”“刚才那个”“继续推荐”等指代表达
```

---

### 6.3 User Decision Memory

位置：

```text
PostgreSQL
```

存：

```text
用户画像
收藏岗位
排除岗位
确认目标岗位
风险偏好
学习进度
```

用途：

```text
个性化推荐
避免重复推荐
动态学习计划
```

---

### 6.4 Agent Experience Memory

位置：

```text
PostgreSQL，后续可扩展 Milvus 索引与集合
```

存 Agent 自己的经验，不存用户隐私：

```text
专业匹配经验
RAG query rewrite 经验
风险抽取漏检经验
推荐失败经验
```

例子：

```json
{
  "scenario": "major_match",
  "trigger": "计算机技术 vs 计算机类",
  "lesson": "优先检索专业目录；无法确认时 need_manual_confirm=true",
  "success_count": 12
}
```

---

### 6.5 Memory 工作流

任务开始：

```text
MemoryRetrievalNode 读取用户记忆、会话记忆、相关经验记忆
```

任务结束：

```text
MemoryConsolidationNode 总结本次任务，只保存有价值的信息
```

不要把所有中间日志都写入长期记忆。

---

## 7. Guardrails：必须实现 3 个

### 7.1 Citation Guard

政策回答必须有引用。没有引用就输出不确定。

### 7.2 Uncertainty Guard

专业匹配不确定时，不能写成“完全匹配”。

### 7.3 Freshness Guard

数据年份不一致时必须提示。

比如：

```text
用户查询 2026 国考，但分数线数据来自 2025 年，应标注：历史参考。
```

---

## 8. Human-in-the-loop

只在 3 个场景触发：

```text
专业匹配 uncertain
风险等级 high
政策依据不足
```

处理方式：

```text
生成 pending_review 记录
前端展示待确认
用户选择：加入推荐 / 排除 / 稍后确认 / 生成咨询话术
```

MVP 不需要复杂审批流。

---

## 9. 前端只做 5 个页面

基于模板 React 前端新增：

```text
1. 用户画像页
2. 数据导入页，管理员
3. 岗位推荐页
4. 推荐报告详情页，含 Agent Trace
5. 政策问答页
```

后续再加学习计划页、飞书设置页。

---

## 10. 后端目录建议：基于模板扩展

在 `backend/app` 下新增：

```text
backend/app/gwy/
  agents/
    graph.py
    state.py
    nodes.py

  skills/
    position.py
    policy.py
    major.py
    risk.py
    ranking.py
    report.py
    guardrails.py
    memory.py
    feishu.py

  mcp_tools/
    position_tools.py
    policy_tools.py
    risk_tools.py
    memory_tools.py
    feishu_tools.py
    trace_tools.py

  services/
    import_service.py
    recommendation_service.py
    rag_service.py
    memory_service.py
    trace_service.py
    feishu_service.py

  evals/
    run_eval.py
    metrics.py

  prompts/
    major_match.md
    risk_extract.md
    policy_answer.md
    report_generate.md
```

在模板已有目录中扩展：

```text
backend/app/models.py        # 增加 Gwy 相关 SQLModel
backend/app/api/routes/      # 增加 gwy 路由
backend/app/core/config.py   # 增加 Milvus、LLM、飞书配置
```

---

## 11. 数据库模型：只先建核心表

新增 SQLModel：

```text
GwyUserProfile
GwyPosition
GwyPolicyDocument
GwyRecommendationTask
GwyRecommendationItem
GwyRiskItem
GwyAgentRun
GwyAgentStep
GwyToolCall
GwyConversationMemory
GwyDecisionMemory
GwyExperienceMemory
GwyHumanReview
```

不要第一版建太多表。

---

## 12. API：只先做核心接口

```text
POST /api/v1/gwy/import/positions
POST /api/v1/gwy/import/policies

POST /api/v1/gwy/profile
GET  /api/v1/gwy/profile/me
PATCH /api/v1/gwy/profile/me

POST /api/v1/gwy/recommendations
GET  /api/v1/gwy/recommendations/{task_id}
GET  /api/v1/gwy/recommendations/{task_id}/trace

POST /api/v1/gwy/policy/query

POST /api/v1/gwy/positions/{position_id}/favorite
POST /api/v1/gwy/positions/{position_id}/reject

GET  /api/v1/gwy/human-reviews/pending
POST /api/v1/gwy/human-reviews/{review_id}/confirm

POST /api/v1/gwy/feishu/push/{task_id}
```

---

## 13. 推荐任务的最终输出

推荐接口返回：

```json
{
  "task_id": "task_xxx",
  "summary": {
    "total_positions": 20810,
    "hard_rule_passed": 326,
    "major_related": 74,
    "high_match": 8,
    "need_confirm": 13
  },
  "recommendations": [
    {
      "rank": 1,
      "position_id": "pos_001",
      "position_name": "信息化管理岗",
      "department_name": "国家税务总局XX市税务局",
      "score": 86,
      "recommend_level": "优先考虑",
      "risk_level": "medium",
      "competition_level": "medium",
      "need_manual_confirm": true,
      "reasons": [],
      "risks": [],
      "citations": []
    }
  ]
}
```

---

## 14. MVP 验收标准

Codex 实现第一版时，满足这些即可：

```text
1. 能导入一份职位表 Excel。
2. 能导入一份报考指南/专业目录文档到 Milvus。
3. 用户能创建画像。
4. 系统能跑完整岗位推荐 LangGraph。
5. 硬条件过滤不用 LLM。
6. 专业匹配能输出 need_manual_confirm。
7. 风险审查能识别备注风险。
8. 政策回答带 citation。
9. 推荐报告能展示 Top 10 和原因。
10. 能保存 Agent Trace。
11. 能推送飞书 Webhook。
12. 能保存用户收藏/排除岗位。
```

---

## 15. 不做的内容

第一版不做：

```text
自动报名
完整刷题系统
申论批改
面试陪练
GUI Agent
复杂多 Agent 自由对话
MiniMind 微调
省考全量数据
微信公众号/小程序
```

这些后续优化。

---

## 16. 后续优化

第二阶段：

```text
学习计划 Agent
Watcher Agent：公告更新监控
Review Agent：报告二次校验
离线评测脚本
MiniMind 风险抽取微调
飞书互动卡片
```

---

## 17. 简历表述

**GwyPilot：基于 Agentic RAG 的公考职位决策 Agent**  
技术栈：Python｜FastAPI｜SQLModel｜PostgreSQL｜React｜LangGraph｜LlamaIndex｜Milvus｜Redis｜MCP｜飞书机器人

项目描述：

面向国考/省考选岗场景，基于 FastAPI 全栈模板二次开发公考职位决策 Agent。系统将职位表、进面分数线等结构化数据存入 PostgreSQL，将招考公告、报考指南和专业目录构建为 Milvus 政策向量库，基于 LangGraph 编排岗位查询、规则过滤、专业匹配、政策 RAG、风险审查、推荐排序和飞书推送流程，实现可解释岗位推荐和风险提示。

主要工作：

- 基于 SQLModel 构建职位表、用户画像、推荐任务、Agent Trace 和用户决策记忆等数据模型。
- 基于 LangGraph 构建状态化岗位推荐工作流，主流程固定编排，专业匹配和风险审查节点引入 ReAct + Reflection。
- 设计 Agentic RAG 检索链路，支持 Query Rewrite、Milvus 向量检索、Rerank、Citation Guard 和政策依据引用。
- 基于规则引擎实现学历、学位、政治面貌、基层经历、应届身份等硬条件过滤，避免全部依赖 LLM。
- 设计风险审查模块，结构化识别专业不确定、最低服务年限、户籍限制、证书要求、工作强度等风险。
- 设计 Agent 长短期记忆，包含 Working Memory、Conversation Memory、User Decision Memory 和 Agent Experience Memory。
- 构建 Agent Trace 可观测模块，记录节点状态、工具调用、检索证据、Reflection 结果和耗时。
- 接入飞书 Webhook，将岗位推荐报告和风险提示推送至飞书。
