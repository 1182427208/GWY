# GwyPilot 岗位分析图设计

日期：2026-05-29

## 目标

把“Excel 式岗位筛选 -> 保存快照 -> 提交分析 -> 生成报告 -> 展示轨迹”做成一条独立分析链路，和聊天问答链路分离。

这个链路要满足三件事：

1. 结构化岗位筛选仍然以 PostgreSQL 为准。
2. 政策、公告、报考指南等证据仍然以 Milvus RAG 为准。
3. Agent 只负责编排流程，不替代规则筛选，也不直接吞掉所有逻辑。

## 设计原则

1. `Skills` 做稳定规则。
   - 负责快照标准化、字段归一、文本格式、固定判断规则。
   - 输出应尽量确定，不依赖模型自由发挥。

2. `Agent` 做流程编排。
   - 负责决定下一步查什么、要不要复核、何时生成报告。
   - 负责把每一步记录成 trace。

3. `Agentic RAG` 做证据支撑。
   - 负责岗位事实、历史分数、招录人数、政策依据、风险依据的检索。
   - 负责解释“为什么这样判断”，而不是单独决定最终排序。

4. 聊天图与分析图分离。
   - 聊天图继续服务日常问答。
   - 分析图专门服务岗位推荐报告。

## 总体架构

### 1. 输入层

岗位分析的输入不是单条自然语言问句，而是一个“分析快照”，至少包含：

- 当前筛选条件
- 当前表格状态
- 当前选中岗位或候选集
- 用户补充信息
- 可选的历史录取分数、招录人数、备注信息

### 2. 规则层

这一层由 `Skills` 负责：

- 快照规范化
- 缺失字段补齐
- 条件归一化
- 生成分析标题、摘要、报告段落模板
- 生成固定的风险标签与结构化结论

### 3. 编排层

这一层由独立的岗位分析 `Agent graph` 负责，建议命名为：

- `position_analysis_graph`

其职责是：

- 判断分析范围
- 调用 PostgreSQL 和 Milvus
- 触发风险复核
- 组织报告生成
- 输出 trace 和最终结果

### 4. 证据层

这一层由 `Agentic RAG` 负责：

- PostgreSQL：
  - 岗位结构化字段
  - 历史录取分数
  - 招录人数
  - 用户补充信息
  - 分析任务和快照记录

- Milvus：
  - 政策
  - 公告
  - 报考指南
  - 专业目录
  - 风险依据

## 推荐流程

### Step 1. 保存快照

用户在 Excel 式岗位表中完成筛选后，保存当前状态。

快照建议包含：

- filters
- sort
- pagination
- search
- selected_rows
- visible_columns
- notes
- user_profile_overrides

### Step 2. 创建分析任务

分析任务记录：

- 快照 id
- 用户 id
- 分析目标
- 状态
- 创建时间
- 当前阶段
- 最终结果摘要

### Step 3. 分析图执行

推荐节点顺序：

1. `load_snapshot`
2. `normalize_snapshot`
3. `build_analysis_scope`
4. `retrieve_position_facts`
5. `retrieve_policy_evidence`
6. `risk_review`
7. `compose_report`
8. `refine_report`
9. `persist_result`

### Step 4. 前端展示

建议单独做分析页，不放在聊天页里。

分析页展示：

- 当前快照摘要
- 报告正文
- 推荐结论
- 风险提示
- 证据来源
- Agent 轨迹
- 历史分析记录

## 各层职责

### Skills 需要承担的内容

建议拆成以下能力块：

- `snapshot_normalize_skill`
- `position_filter_normalize_skill`
- `analysis_scope_build_skill`
- `report_outline_skill`
- `report_text_cleanup_skill`
- `risk_label_skill`
- `citation_dedup_skill`

这些函数都应尽量纯函数化，便于单测。

### Agent 需要承担的内容

岗位分析 Agent 负责：

- 读取快照
- 决定分析路径
- 调用检索
- 调用风险复核
- 调用报告生成
- 汇总 trace

Agent 不负责：

- 直接做岗位库的硬筛选规则
- 直接替代 PostgreSQL 查询
- 直接代替 RAG 检索

### Agentic RAG 需要承担的内容

它负责：

- 对岗位事实做补充检索
- 对政策条款做证据检索
- 对风险点做证据核查
- 对报告结论提供引用

它不应该：

- 替代规则层
- 把所有步骤都交给模型自由生成
- 让结论脱离结构化数据

## 数据结构建议

### 分析任务

建议新增或扩展一张分析任务表，保存：

- task_id
- user_id
- snapshot_id
- status
- stage
- input_json
- output_json
- report_text
- trace_json
- created_at
- updated_at

### 分析轨迹

轨迹建议是结构化列表，每一项至少包含：

- step
- status
- detail
- elapsed_ms
- inputs_summary
- outputs_summary
- evidence_refs

不要只存一段大字符串。

## API 建议

建议保留现有岗位表接口，同时新增分析接口：

- `POST /api/v1/gwy/analysis/snapshots`
- `POST /api/v1/gwy/analysis/tasks`
- `GET /api/v1/gwy/analysis/tasks/{task_id}`
- `GET /api/v1/gwy/analysis/tasks/{task_id}/trace`
- `GET /api/v1/gwy/analysis/tasks/{task_id}/report`

如果快照和任务暂时合并，也可以先用一个“创建分析任务”接口携带完整快照。

## 现有代码复用点

当前仓库里已有可复用能力：

- [岗位表筛选与分析服务](/e:/GwyPilot/GwyPilot/backend/app/gwy/services/position_catalog_service.py)
- [岗位推荐 Agent](/e:/GwyPilot/GwyPilot/backend/app/gwy/agents/position_decision_agent.py)
- [风险复核 Agent](/e:/GwyPilot/GwyPilot/backend/app/gwy/agents/risk_review_agent.py)
- [报告生成 Agent](/e:/GwyPilot/GwyPilot/backend/app/gwy/agents/report_generator_agent.py)
- [现有 Skills](/e:/GwyPilot/GwyPilot/backend/app/gwy/skills/position_recommendation_skills.py)
- [现有 Policy RAG 图](/e:/GwyPilot/GwyPilot/backend/app/gwy/services/policy_rag_service.py)

这些代码不需要推倒重来，优先做“重组和收口”。

## 前端设计建议

前端建议拆成两个清晰页面：

1. 岗位筛选页
   - 类 Excel 体验
   - 保存当前筛选状态
   - 发起分析任务

2. 分析报告页
   - 展示报告结果
   - 展示 Agent trace
   - 展示证据引用
   - 展示任务历史

不要把分析报告混进聊天输入区，也不要让聊天页承担岗位分析大屏功能。

## 风险与约束

1. 不要让 `Agent` 直接替代规则层。
2. 不要让 `RAG` 直接决定岗位筛选结果。
3. 不要把岗位分析和日常问答共用一条状态流。
4. 不要在没有证据时输出绝对结论。
5. 不要暴露不可审计的原始模型内部思维链；应输出可追踪的阶段轨迹和证据摘要。

## 测试建议

建议至少补三类测试：

1. `Skills` 单测
   - 快照归一
   - 报告摘要格式
   - 风险标签规则

2. Agent 流程测试
   - 分析图节点顺序
   - 证据命中
   - 轨迹记录

3. API 测试
   - 创建分析任务
   - 查询任务详情
   - 查询报告和轨迹

## 验收标准

满足以下条件即可认为这版设计成立：

1. 用户可以从岗位筛选页保存一个快照。
2. 系统可以基于快照创建独立分析任务。
3. 分析任务会经过独立的 Agent graph。
4. 报告里能看到 PostgreSQL 与 Milvus 提供的证据。
5. 前端能单独展示报告和轨迹。
6. 聊天页和分析页彼此不互相污染。

## 待确认问题

1. 历史录取分数目前存放在哪张表，或者是否需要单独导入。
2. 分析任务是否需要支持异步队列，还是先同步执行。
3. 轨迹页面是否需要分页加载大报告。

