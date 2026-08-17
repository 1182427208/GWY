# GwyPilot Agent Loop 重构方案 B 设计

日期：2026-08-01

## 背景

本方案参考 `hello-agents/docs/chapter4/第四章 智能体经典范式构建.md` 中对 ReAct、Plan-and-Solve、Reflection 的定义，目标不是推翻现有系统，而是把当前 `AgentRuntime` 主循环改造成“主 Agent 负责规划与调度，子 Agent 负责单域执行，子 Agent 内部融合 ReAct 与 Reflection”的结构。

当前项目已经具备这些基础：

- 顶层 `AgentRuntime` 主循环已经存在。
- 工具调用、权限控制、异常恢复、trace 记录已经跑通。
- 岗位推荐、政策 RAG、网页核验、风险复核、报告生成、学习计划已经分别实现。

但目前的问题也很明显：

- 子 Agent 数量多，职责边界不够硬。
- 有些子 Agent 既做规划又做执行又做校验，容易互相重叠。
- ReAct、Plan-and-Solve、Reflection 已经“局部出现”，但没有被组织成统一的主从结构。
- 浏览器工具当前不可用时，网页核验路径的降级语义还不够清晰，容易把“工具失效”和“证据缺失”混在一起。

本方案的目标是把这些零散能力重新编排，而不是重写工具层。

## 方案定位

方案 B 的核心是“一个主 Agent，多个职责单一的子 Agent”。

主 Agent 做三件事：

- 把用户输入转成可执行计划。
- 根据计划选择一个或多个子 Agent。
- 收集子 Agent 输出后决定下一步，直到任务结束。

子 Agent 做一件事：

- 针对单一任务域，自主判断需要从 PostgreSQL、Milvus、网页或缓存中取什么信息，并在结果基础上自我校验后返回结构化输出。

这意味着：

- 主 Agent 体现 Plan-and-Solve。
- 子 Agent 体现 ReAct + Reflection。
- 现有工具调用、权限控制、异常处理保持不变。

## 参考框架映射

| 经典框架 | 在本方案中的落点 |
|---|---|
| ReAct | 子 Agent 内部的“任务分析 -> 选择来源 -> 调用工具 -> 观察结果 -> 再分析 -> 产出结论”循环 |
| Plan-and-Solve | 主 Agent 在启动时通过 `todo_write` 写计划，并把复杂任务拆成若干子任务 |
| Reflection | 子 Agent 在输出前做一次自检，检查证据是否足够、是否缺少来源、是否需要补抓 |

## 总体架构

### 1. 主 Agent

主 Agent 仍然保留在 `AgentRuntime` 这一层，不改变工具调用协议、trace 结构和权限门控。

主 Agent 的职责从“自己尽量做完一切”收敛为：

- 读取用户输入。
- 生成 `todo_write` 计划。
- 识别任务类型。
- 路由到合适的子 Agent。
- 聚合子 Agent 的返回结果。
- 决定是否继续下一轮、补充证据、切换子 Agent，或直接收尾。

### 2. 子 Agent

建议把当前能力收敛为少量边界明确的子 Agent：

- `PolicyResearchAgent`：只负责政策、公告、报考指南、专业目录、资格条件的证据收集与回答草稿。
- `PositionResearchAgent`：只负责 PostgreSQL 岗位事实、结构化筛选、岗位历史补证。
- `WebEvidenceAgent`：只负责网页检索、抓取、浏览器回退和证据整理。
- `RiskReviewAgent`：只负责对候选岗位做风险与隐性条件核验。
- `ReportWriterAgent`：只负责把已确认的结构化结果写成最终 Markdown 报告。
- `StudyPlanAgent`：只负责生成学习计划，不掺杂岗位筛选逻辑。

这些子 Agent 不再按“固定步骤图”去绑定死流程，而是按“任务分析 -> 自主决定取证方式 -> 结果核验 -> 输出”执行。

### 3. 工具层

工具层不改：

- 工具名不改。
- 权限策略不改。
- 失败重试与 fallback 不改。
- trace 事件格式尽量不改。

变化发生在“谁来决定调用哪个工具、以及何时结束”。

## 子 Agent 的执行方式

每个子 Agent 都采用一个轻量的内部 ReAct / Reflection 结构，但不是完整的 LangGraph 大图。

推荐的内部节奏是：

1. 任务分析：判断当前任务需要哪些信息。
2. 来源选择：决定优先查 PostgreSQL、Milvus、网页，还是直接使用已有 state。
3. 工具调用：按需调用现有工具。
4. 观察与判断：读取工具返回，判断是否足够。
5. 反思校验：检查是否缺证据、是否有矛盾、是否需要补抓。
6. 输出结构化结果：返回 `answer`、`evidence`、`missing`、`confidence`、`next_actions`。

这里的 Reflection 不是独立长循环，而是一次输出前的质量门。

## 计划与调度

主 Agent 在接到用户请求后，必须先做计划，不允许直接进入“看见什么就做什么”的模式。

建议用以下计划字段作为统一约束：

- `task_kind`
- `subtasks`
- `owner_agent`
- `target_sources`
- `expected_outputs`
- `stop_condition`
- `fallback_condition`

这样 `todo_write` 不只是展示给用户看的任务清单，而是主 Agent 的调度合同。

## 路由规则

主 Agent 根据任务类型决定子 Agent：

- 政策类问题 -> `PolicyResearchAgent`
- 岗位筛选 / 岗位历史 / 竞争信息 -> `PositionResearchAgent`
- 网页证据不足 -> `WebEvidenceAgent`
- 风险与隐性条件核验 -> `RiskReviewAgent`
- 最终报告整理 -> `ReportWriterAgent`
- 复习规划 -> `StudyPlanAgent`

如果一次任务跨多个域，主 Agent 按顺序调用多个子 Agent，但每个子 Agent 只做自己的部分。

## 浏览器工具问题的处理

当前浏览器工具不可用时，不建议把问题归因到上层编排。

本方案建议把网页能力拆成三层降级：

- 第一层：搜索引擎结果。
- 第二层：HTTP 抓取。
- 第三层：浏览器渲染回退。

如果第三层不可用，子 Agent 必须明确输出：

- 当前网页证据不足。
- 已尝试的查询词。
- 已获得的低置信度证据。
- 需要人工复核的页面。

也就是说，浏览器不可用不应导致整个 Agent Loop 崩掉，只应降低网页证据的置信度。

## 结果格式

每个子 Agent 返回统一结构，便于主 Agent 收敛：

- `status`
- `answer`
- `evidence`
- `missing`
- `confidence`
- `next_actions`
- `trace`

其中：

- `answer` 给主 Agent 读。
- `evidence` 给报告和评测读。
- `missing` 用于决定是否继续执行。
- `confidence` 用于反思门控。
- `next_actions` 用于主 Agent 决策下一轮。

## 与现有代码的关系

方案 B 不是重写，而是收敛：

- 保留 `AgentRuntime` 作为主循环。
- 保留现有工具注册、权限、异常恢复、trace。
- 将当前分散在各 service / agent 里的“规划、执行、反思”逻辑统一抽到更少的子 Agent 中。
- 把原来很多“写死的流程节点”改成“可分析、可选源、可反思”的执行单元。

## 实施边界

本方案明确不做这些事：

- 不新增新的工具协议。
- 不改变权限白名单 / 黑名单。
- 不替换 PostgreSQL 结构化筛选。
- 不把 RAG 变成岗位筛选器。
- 不把所有子 Agent 再拆成更细的碎片。

## 推荐迁移路径

建议按这个顺序改：

1. 先定义统一的子 Agent 输出合同。
2. 再收敛子 Agent 职责边界。
3. 然后把主 Agent 改为先计划、再分派、再收尾。
4. 最后为每个子 Agent 加一次 Reflection 门。

这样能最大程度保持系统可运行。

## 测试策略

建议补这些测试：

- 主 Agent 的计划是否总是先于执行。
- 子 Agent 的职责是否互不重叠。
- 网页降级是否能返回明确的 `missing` 和 `confidence`。
- 风险复核是否只读，不越权。
- 报告是否只能消费已经确认的结构化结果。
- trace 是否仍然完整可回放。

## 验收标准

满足以下条件，就可以认为方案 B 成立：

- 用户请求先生成计划，再触发子 Agent。
- 子 Agent 只负责单域任务，不再兼做多个领域的决策。
- 子 Agent 返回的结果中包含证据、缺口、置信度和下一步动作。
- 主 Agent 会根据子 Agent 的结果继续下一轮，而不是一次性拍死结论。
- 工具调用、权限控制、异常处理保持现有行为。

