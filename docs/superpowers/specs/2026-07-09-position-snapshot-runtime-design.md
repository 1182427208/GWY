# 快照驱动的岗位推荐 AgentRuntime 设计

## 目标

把岗位推荐和岗位分析统一到“先固定快照，再由 AgentRuntime 分析”的流程里。

当用户在聊天里提出岗位推荐，但当前没有固定岗位快照时，系统不再直接做一套轻量推荐，而是引导用户先到岗位表筛选并固定快照。只要快照存在，聊天入口和岗位分析任务入口都调用同一套快照驱动的 AgentRuntime：先让模型制定分析计划，再按需调用工具核查岗位事实、政策证据和风险，最后生成报告、复习计划，并在任务完成后沿用现有飞书推送能力。

## 非目标

- 不新增前端页面。
- 不用 RAG 替代 PostgreSQL 的结构化岗位筛选。
- 不立即删除现有 `PositionAnalysisAgent`；新 runtime 稳定前把它保留为 fallback。
- 不改变 `full-stack-fastapi-template` 的原有项目骨架和启动方式。

## 架构设计

新增一个面向岗位快照的 runtime 服务，暂定名为 `PositionSnapshotRuntimeService`，放在 `backend/app/gwy/services/`。

这个服务负责：

- 构建一个专用于“快照岗位分析”的 `AgentRuntime`。
- 把岗位快照、用户画像、任务 ID、年份、考试类型和已有推荐上下文注入 runtime state。
- 注册一组让模型读取快照、分析岗位和生成最终产物的工具。
- 返回兼容 `PositionAnalysisService` 的结果结构，包括 `status`、`stage`、`report`、`trace`、`output_json`、`recommendations`、`risk_review`、`study_plan`、`needs_more_info` 等字段。

`PositionAnalysisService` 后续不再直接调用 `PositionAnalysisAgent` 作为主流程，而是优先调用 `PositionSnapshotRuntimeService`。如果 runtime 因模型 tool-call 不可用、供应商异常或其他执行错误失败，则记录恢复轨迹，并 fallback 到现有 `PositionAnalysisAgent`，避免岗位分析任务整体不可用。

## Runtime 工具

runtime 复用现有 `register_builtin_tools` 中的通用工具，尤其是：

- `todo_write`：要求模型在非简单分析前先列出 2-5 步分析计划。
- `load_skill`：加载岗位规划相关 runtime skill。
- context 和 memory 工具：保留上下文检查点和会话记忆能力。

新增服务注册快照专用工具：

- `load_snapshot`：加载并摘要固定快照，包括已选岗位 ID、可见列、筛选条件、备注和来源表。
- `analyze_snapshot_positions`：基于快照岗位 ID 和用户画像调用 PostgreSQL 岗位目录分析，确保岗位事实来自结构化表。
- `search_policy_evidence`：在资格限制、政策依据、考试规则等场景下检索政策证据。
- `review_position_risks`：调用现有风险复核 Agent，检查岗位限制和资格风险。
- `generate_study_plan`：调用现有复习计划 Agent，并把生成的 Markdown 写入 runtime state。
- `compose_snapshot_report`：让模型基于 runtime state、岗位事实、风险复核、政策证据和复习计划组合或润色最终 Markdown 报告。

runtime 系统提示应明确要求：

- 非简单分析必须先调用 `todo_write` 制定计划。
- 岗位筛选和岗位事实必须以 PostgreSQL 结构化数据为准。
- 政策、资格限制和报考规则需要政策证据支撑。
- 无法确认的数据必须标注为“未知”或“无法确认”，不能编造。
- 最终报告面向用户输出中文 Markdown，不暴露内部 JSON。

## 聊天入口集成

聊天里的岗位推荐改成快照优先：

- 如果用户询问岗位推荐，但请求里没有固定快照或任务上下文，则返回明确引导：请先在岗位表筛选岗位并固定快照，再让 Agent 做分析。
- 如果已有快照或任务上下文，则调用和岗位分析任务相同的 `PositionSnapshotRuntimeService`。

这样可以避免聊天推荐和岗位分析任务各跑一套逻辑，导致推荐结果、报告结构和 trace 不一致。

## 持久化与轨迹

保留现有持久化行为：

- `GwyPositionAnalysisTask.report_text` 保存最终报告。
- `GwyPositionAnalysisTask.trace_json` 保存 runtime trace。
- `GwyPositionAnalysisStep` 继续从 trace 中拆分步骤记录。
- 报告 Markdown 继续归档到 `data/gwy_analysis_reports/`。
- 从岗位分析任务生成的复习计划继续由 `StudyPlanService` 持久化。
- 飞书推送仍由 `PositionAnalysisService` 在任务完成后统一处理。

runtime trace 应保留 AgentRuntime 的事件名，例如 `UserPromptSubmit`、`LLMStart`、`ToolUse`、`PostToolUse`、`Stop`，以及具体工具 step。可以通过一个轻量 adapter 映射到现有 `GwyPositionAnalysisStep` 的字段格式。

## 错误处理

- 聊天入口没有快照时，不运行 fallback 岗位推荐，只引导用户创建快照。
- 岗位分析任务中 runtime 执行失败时，记录 error recovery trace，并 fallback 到 `PositionAnalysisAgent`。
- 如果快照或用户画像信息不足，则返回 `needs_more_info`、缺失字段和追问问题，而不是强行生成报告。
- 如果飞书 webhook 未配置，继续沿用现有 skipped push 行为。

## 测试范围

新增聚焦的后端测试：

- 聊天岗位推荐没有快照时，返回固定快照引导，并且不调用 PostgreSQL 推荐。
- 执行岗位分析任务时，`PositionAnalysisService` 优先调用快照 runtime。
- runtime 抛错时，服务 fallback 到旧 `PositionAnalysisAgent`。
- runtime 结果能写入任务报告、trace、output JSON 和报告归档。
- 分析成功或跳过飞书时，飞书推送仍会追加对应 trace。

## 推进方式

先在服务边界后面引入 runtime 主流程，保留旧 `PositionAnalysisAgent` 作为兜底。等新流程稳定并通过测试后，再考虑清理旧的模板化分析逻辑。
