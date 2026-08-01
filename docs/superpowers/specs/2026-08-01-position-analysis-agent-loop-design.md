# 岗位分析 Agent Loop 设计

## 目标

让岗位分析从“硬筛选结果加风险罗列”升级为可直接支持报考决策的 Agent Loop。顶层继续使用 `AgentRuntime` 自主决定工具调用；岗位研究、政策检索、风险复核和报告审查等专项能力由工具封装的子 agent 完成，子 agent 内部可以继续使用 LangGraph。

## 运行边界

岗位表的结构化筛选仍以 PostgreSQL 为准，RAG 只补充政策、专业目录和报考指南证据。Runtime 必须先加载岗位分析 skill 并写入计划，再按工具返回的 `missing`、`confidence` 和 `next_actions` 继续补证。缺少证据时只能输出未知或无法确认，不得生成报录比、进面分或录取概率等虚构数值。

## 工具契约

岗位分析工具的结果统一包含：

```json
{
  "status": "complete|partial|failed",
  "covered": [],
  "missing": [],
  "confidence": "high|medium|low|unknown",
  "next_actions": [],
  "data": {}
}
```

现有岗位筛选和风险工具继续保留，但需要把研究结果写入 Runtime state。新增岗位历史研究、隐性条件核验、决策矩阵和报告质量校验能力。报告工具只能消费决策矩阵、证据覆盖和核验任务，不再只消费原始 recommendations 与 risk_review。

## 决策矩阵

每个岗位生成结构化决策项，至少包含 `tier`、`fit_score`、`competition_level`、`preparation_cost`、`confidence`、`reasons`、`risks`、`unknowns`、`verification_tasks` 和 `decision_change_rules`。岗位层级为 `冲刺`、`主攻`、`保底`、`谨慎` 或 `排除`。层级必须由硬条件状态、个人匹配、历史竞争信息、备考成本和证据完整度共同决定；缺少关键竞争数据时降低置信度并生成补证任务，不能伪造估算。

## 报告要求

报告必须先给最终选岗结论，再给梯度表和横向比较。每个岗位说明层级理由、最大风险、数据置信度、核验材料、核验动作及核验后可能如何改变结论。报告不得把所有岗位都写成推荐，不得重复展示同类风险，不得用“请人工复核”替代具体任务。

## 验收标准

1. Runtime skill 中的工具名称与注册工具一致，并明确报告前的必要步骤。
2. 工具返回缺口后，Runtime prompt 明确要求继续调用对应工具，不能直接生成最终报告。
3. 决策矩阵能稳定区分硬条件不满足、信息不足、竞争可控和竞争过热岗位。
4. 风险按岗位和风险类型去重，并返回可执行核验任务。
5. 报告质量校验能拒绝无结论、无分层、无比较或只有泛化人工复核的报告。
