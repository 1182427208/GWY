# GwyPilot Agent Loop 重构方案 C 设计

日期：2026-08-01

## 背景

本方案同样参考 `hello-agents/docs/chapter4/第四章 智能体经典范式构建.md`，但比方案 B 更强调整体流程的清晰分层。

如果说方案 B 是“一个主 Agent + 若干职责单一的子 Agent”，那么方案 C 是“显式分层的四段式流水线”。

现有项目的问题不在于有没有能力，而在于这些能力混在一起：

- 主循环和子流程边界模糊。
- 规划、执行、核验、报告经常在同一层里交叉出现。
- 子 Agent 职责之间有重叠，导致维护时不好判断应该改哪一层。

方案 C 的目标是把这些职责彻底分层，让系统变成更稳定、可测、可替换的流水线。

## 方案定位

方案 C 的核心是四个明确角色：

- `PlannerAgent`
- `ExecutorAgent`
- `VerifierAgent`
- `ReporterAgent`

外面再套一层主协调器，仍然由 `AgentRuntime` 驱动，但主协调器只负责路由和收口，不直接承担具体业务推理。

这个结构更接近 chapter4 里三种范式的组合：

- `PlannerAgent` 对应 Plan-and-Solve 的 Plan。
- `ExecutorAgent` 对应 ReAct 的 Thought-Action-Observation。
- `VerifierAgent` 对应 Reflection 的 Execute-Reflect-Refine。
- `ReporterAgent` 负责把已经收敛的结果整理成最终输出。

## 参考框架映射

| 经典框架 | 在本方案中的落点 |
|---|---|
| ReAct | `ExecutorAgent` 的内部执行循环 |
| Plan-and-Solve | `PlannerAgent` 先生成完整任务分解和来源计划 |
| Reflection | `VerifierAgent` 对 `ExecutorAgent` 的输出做独立审查和修正 |

## 总体架构

### 1. Coordinator

Coordinator 仍然保留 `AgentRuntime` 作为入口，但它只做：

- 接收用户输入。
- 调用 `PlannerAgent` 生成计划。
- 按计划调用 `ExecutorAgent`。
- 把执行结果送入 `VerifierAgent`。
- 通过 `ReporterAgent` 输出最终答案。

它不直接做复杂业务判断，最多只处理：

- 何时结束。
- 是否要重跑某一步。
- 是否需要切换数据源。

### 2. PlannerAgent

PlannerAgent 的职责是“先把问题想清楚”。

它输出的不是答案，而是计划：

- 任务分解。
- 每一步需要的来源。
- 每一步的期望输出。
- 该步骤是否需要网页、PostgreSQL、Milvus 或缓存。
- 是否需要先写 `todo_write`。

PlannerAgent 必须是 Plan-and-Solve 风格，不能直接调用大量业务工具。

### 3. ExecutorAgent

ExecutorAgent 是真正干活的地方。

它不按 LangGraph 预先写死每个步骤，而是根据 PlannerAgent 交给它的任务，自主决定：

- 先查什么。
- 需要哪个工具。
- 是否要换查询词。
- 是否需要补抓网页。
- 何时认为当前信息够了。

这部分是 ReAct 的核心实现，但内部也保留一次轻量反思：

- 工具结果是否匹配目标。
- 结果是否存在冲突。
- 结果是否需要补证。

### 4. VerifierAgent

VerifierAgent 是 Reflection 的实现者。

它不负责查资料，而是审查 ExecutorAgent 的结果：

- 是否有证据支撑。
- 是否存在明显幻觉或推断过头。
- 是否缺失关键字段。
- 是否存在来源冲突。
- 是否需要回到 ExecutorAgent 重新执行。

VerifierAgent 的输出只有三类：

- `approve`
- `revise`
- `escalate`

### 5. ReporterAgent

ReporterAgent 只负责最终文稿，不负责推理和取证。

它消费的是已经被验证过的结构化结果，输出最终 Markdown：

- 直接结论。
- 判断依据。
- 风险提醒。
- 下一步建议。

## 流水线节奏

方案 C 的主流程建议固定为：

1. `todo_write` 写计划。
2. `PlannerAgent` 生成任务分解。
3. `ExecutorAgent` 执行第一个子任务。
4. `VerifierAgent` 审查结果。
5. 如果通过，进入下一个子任务或 `ReporterAgent`。
6. 如果不通过，回到 `ExecutorAgent` 重新执行。
7. 最终由 `ReporterAgent` 输出答案。

这个结构比方案 B 更“硬”，优点是稳定，代价是更像流水线。

## 子 Agent 边界

方案 C 对子 Agent 的边界比方案 B 更严格：

- `PlannerAgent` 不碰工具。
- `ExecutorAgent` 只碰数据和工具，不做最终结论裁决。
- `VerifierAgent` 不做事实检索，只做审查和修正建议。
- `ReporterAgent` 不重新取证，只整合已经确认的材料。

这样做的好处是：

- 容易测。
- 容易替换。
- 容易知道错误发生在哪一层。

## 浏览器工具问题的处理

浏览器工具不可用的问题，在方案 C 中要被明确限制在 `ExecutorAgent` 内部的网页分支里。

处理方式建议是：

- `ExecutorAgent` 先尝试搜索和 HTTP 抓取。
- 如果需要浏览器渲染但工具不可用，记录为 `browser_unavailable`。
- `VerifierAgent` 只能看到这一事实，不应把它当成结论失败。
- `ReporterAgent` 需要明确写出“网页证据不足，已降级处理”。

这样能避免浏览器不可用把整条流水线拖死。

## 结果合同

为了保证四段式流水线能稳定协作，建议统一结果格式：

- `PlannerOutput`
- `ExecutionOutput`
- `VerificationOutput`
- `ReportOutput`

每一层都应该有：

- `status`
- `summary`
- `evidence`
- `missing`
- `confidence`
- `trace`

其中：

- `PlannerOutput` 强调任务拆分。
- `ExecutionOutput` 强调工具与证据。
- `VerificationOutput` 强调审查结论。
- `ReportOutput` 强调最终可读文本。

## 与现有代码的关系

方案 C 对现有代码的要求更高，但仍然不改变这些底层约束：

- 不改工具协议。
- 不改权限门控。
- 不改异常恢复。
- 不改 trace 事件的基本记录方式。

它改变的是：

- 主循环怎么分层。
- 业务逻辑放在哪一层。
- 哪一层有权做什么事。

## 适用场景

方案 C 更适合这些任务：

- 需要较长推理链的岗位分析。
- 需要明显取证、核验和反复修正的政策问答。
- 需要高可靠性的最终报告生成。
- 需要明确知道问题卡在哪一层的排障场景。

如果任务很短、很快、很轻，方案 C 会显得稍重。

## 风险与代价

方案 C 的代价主要有四个：

- 调用层数更多，延迟更高。
- 模块更多，初始化和传参更复杂。
- 需要更严格的输入输出合同。
- 每一层都需要单独写测试，否则容易互相误伤。

因此它是一个“更干净，但更重”的版本。

## 测试策略

建议重点覆盖这些测试：

- `PlannerAgent` 是否稳定生成可执行计划。
- `ExecutorAgent` 是否能按计划自主选择数据源。
- `VerifierAgent` 是否能识别证据不足、冲突或幻觉。
- `ReporterAgent` 是否只消费已验证结果。
- 当浏览器工具不可用时，执行层是否正确降级。
- 当某层失败时，是否能把错误精确回传给协调器。

## 验收标准

方案 C 达标的标志是：

- 每一层职责都很清楚，不互相越界。
- Planner 不做执行，Executor 不做裁决，Verifier 不做取证。
- 主 Agent 只负责调度和收口。
- 复杂任务可以一层层追踪到问题点。
- 现有工具、权限、异常处理不需要重写。

## 与方案 B 的区别

方案 C 比方案 B 更严格的地方在于：

- 方案 B 允许子 Agent 内部更灵活地决定怎么查、怎么想、怎么收尾。
- 方案 C 则把流程拆成明确角色，减少自由度，换来更强的可控性。

如果说方案 B 更像“受控自治”，方案 C 就更像“结构化流水线”。

