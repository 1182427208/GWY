# GwyPilot Agent 评测能力与 Agent Loop 集成说明

> 文档日期：2026-08-01  
> 适用范围：当前仓库中已经实现的 GwyPilot Agent 评测能力、在线评测记录、离线数据集评测，以及它们与 Agent Loop 的结合方式。

## 1. 这套评测现在解决什么问题

当前实现的评测模块，不是一个独立的大型 Benchmark 平台，而是 GwyPilot 自己的“可追踪、可回放、可落库”的轻量评测层。它主要回答四类问题：

1. Agent 有没有把任务做完。
2. Agent 有没有调用对的工具、用了对的参数。
3. 对于政策问答、岗位推荐、记忆更新等场景，结果是否符合预期。
4. 这次运行的 trace、耗时、工具调用次数、token 等工程指标是什么。

它的定位很明确：

- 评测服务于当前 Agent 应用本身。
- 不重构主流程。
- 不引入独立 Reviewer Agent / Evaluation Agent。
- 默认以确定性 scorer 为主，LLM Judge 目前只是预留，不是主路径。

---

## 2. 当前已经实现的评测能力

### 2.1 评测数据模型

评测数据结构集中在 `backend/app/gwy/evals/schemas.py`，核心对象有：

- `EvalCase`：单个评测样本。
- `ExpectedOutcome`：样本的期望结果。
- `AgentObservation`：一次 Agent 运行的标准化观测。
- `ScoreBundle`：单项评分结果。
- `CaseResult`：一次 case 的最终结果。
- `EvalConfig`：离线实验配置。

这些对象已经覆盖了当前评测的主要输入输出：

- 任务类型：`job_filter`、`policy_qa`、`tool_call`、`memory`、`e2e`
- 期望工具、禁用工具、工具参数
- 岗位命中 / 排除岗位
- RAG gold doc / gold chunk / answer points
- memory_after 期望
- clarification / report / Feishu 等任务完成条件
- trace、tool_calls、latency、token、cost 等运行信息

### 2.2 评测模式

当前有两种运行方式：

#### 离线数据集评测

入口在 `backend/app/gwy/evals/run_eval.py` 的 `run_evaluation()`。

它会：

1. 从 jsonl 数据集加载 `EvalCase`
2. 调用传入的 `agent_runner`
3. 把输出统一归一化成 `AgentObservation`
4. 按 case 选择 scorer
5. 写出结果文件和汇总文件

离线评测会输出：

- `results.jsonl`
- `failures.jsonl`
- `summary.json`
- `summary.csv`
- `report.md`
- `config.snapshot.yaml`

#### 在线评测记录

入口在 `backend/app/gwy/evals/service.py` 的 `record_online_evaluation()`。

它会把已经完成的 Agent 输出直接转成一条在线评测记录，落到数据库里。这个路径更贴近真实业务运行，适合在对话、岗位分析等实际流程里顺手采样评测。

#### 内置数据集导入

`import_builtin_eval_datasets()` 会把仓库自带的 `dev.jsonl` 和 `holdout.jsonl` 导入成数据库中的评测集，供前端页面和数据集评测直接使用。

---

## 3. 现在有哪些 scorer，分别评什么

当前 scorer 在 `backend/app/gwy/evals/scorers/` 下，已经实现的有 6 类：

| scorer | 评什么 | 主要指标 |
| --- | --- | --- |
| `task_success` | 任务是否完成 | `success` |
| `tool_call` | 工具调用是否符合预期 | `required_tool_recall`、`tool_precision`、`tool_f1`、`forbidden_tool_violation_rate`、`argument_accuracy` |
| `job_constraint` | 岗位硬约束是否被违反 | `constraint_violation_rate`、`job_precision`、`job_recall`、`job_f1` |
| `rag` | 政策检索与引用是否正确 | `recall_at_k`、`citation_support_rate`、`answer_point_coverage` |
| `memory` | 记忆更新与读取是否正确 | `memory_field_accuracy`、`memory_update_accuracy`、`leakage_count`、`stale_field_usage_count` |
| `efficiency` | 工程效率表现 | `tool_call_count`、`agent_steps`、`latency_ms`、`input_tokens`、`output_tokens`、`estimated_cost` |

### 3.1 task_success

`task_success` 是最基础的成功判定：

- `observation.status == error` 时失败
- `expected_final_status` 不匹配时失败
- 需要报告但最终回答为空时失败
- 需要澄清但没有给出澄清信号时失败
- 需要飞书推送但没有推送成功时失败

### 3.2 tool_call

`tool_call` 负责检查：

- 是否调用了 required tools
- 是否调用了 forbidden tools
- 是否超过 maximum_tool_calls
- 工具参数是否命中期望字段
- 是否出现 forbidden_arguments

这部分是 Agent Loop 的“工具纪律”评测。

### 3.3 job_constraint

`job_constraint` 主要用于岗位推荐场景，检查：

- 返回岗位是否命中 expected job ids
- 是否返回了 forbidden job ids
- 是否违反硬约束，例如：
  - 政治面貌
  - 专业要求
  - 学历要求
  - 学位要求
  - 基层经历要求

它是“结构化岗位筛选是否正确”的核心 scorer。

### 3.4 rag

`rag` 主要用于政策问答，检查三个层面：

- `recall_at_k`：gold doc / gold chunk 是否进入 Top-K
- `citation_support_rate`：回答中的引用是否被 gold ids 支持
- `answer_point_coverage`：最终答案是否覆盖了 expected answer points

这意味着当前的 RAG 评测不是只看“有没有答”，而是同时看：

- 检索有没有召回到
- 引用有没有站得住
- 答案有没有覆盖关键点

### 3.5 memory

`memory` 负责检查：

- `memory_after` 是否更新到了预期字段
- 是否发生 memory leakage
- 是否使用了 stale fields
- memory 更新准确率是否达标

这部分用于验证记忆系统是不是“真在工作”，而不是只在最终回答里看起来像记住了。

### 3.6 efficiency

`efficiency` 是工程维度的观测指标，不直接判失败，但会记录：

- 工具调用次数
- Agent 步数
- latency
- input / output token
- estimated cost

它更像“工程评估”的底盘指标。

---

## 4. 在线评测记录是怎么存的

在线评测走的是数据库落库，相关表和返回结构已经接上。

### 4.1 数据库存储对象

当前在线 / 数据集评测会落到：

- `GwyEvalRun`
- `GwyEvalCaseResult`
- `GwyEvalDataset`

其中：

- `GwyEvalRun` 存一轮评测的总体信息
- `GwyEvalCaseResult` 存单个 case 的评分与观测
- `GwyEvalDataset` 存数据集定义和样本

### 4.2 在线评测记录内容

`record_online_evaluation()` 会把：

- source_type
- source_id
- query
- output
- profile
- expected

转成一条 `EvalCase`，再把输出归一化成 `AgentObservation`，然后调用 `evaluate_online_observation()`。

最终写入的 run 里，会包含：

- `status`
- `trace_complete`
- `scores`
- `failure_reasons`
- `report_text`

case 级结果会包含：

- `scores_json`
- `observation_json`
- `failure_reasons`
- `trace_json`

---

## 5. 离线数据集评测是怎么跑的

离线评测的入口是 `run_evaluation()`。

### 5.1 数据集加载

数据集文件是 jsonl 格式，每行一个 `EvalCase`。

### 5.2 case 执行

运行时会把每个 case 交给一个 `agent_runner`。这让评测层和业务 Agent 主体解耦：

- 评测层只负责加载、执行、评分、写结果
- 具体跑哪个 Agent，可以在外部注入

### 5.3 自动选择 scorer

`score_case()` 会根据 case 的任务类型和 expected 内容自动选择评分项：

- 始终跑 `task_success`
- 有工具相关要求时跑 `tool_call`
- job_filter 跑 `job_constraint`
- policy_qa 跑 `rag`
- memory 或 memory_after 跑 `memory`
- 始终补一个 `efficiency`

这意味着离线评测不是“固定一套分数”，而是按任务需要动态拼装指标。

---

## 6. 评测与 Agent Loop 的结合方式

这是这套实现里最关键的一段。

### 6.1 Agent Loop 的共同底座

`backend/app/gwy/agent_runtime/loop.py` 是通用 Agent Loop。

它做的事情是：

- 接收 system prompt 和 tools registry
- 管理多轮消息
- 处理 memory side query
- 处理 compact / auto_compact
- 处理 LLM 调用恢复
- 处理 tool calls
- 记录完整 trace
- 返回最终 `answer`、`trace`、`state`、`messages`

当前 loop 的 trace 不是“顺手记一点日志”，而是核心产品能力的一部分。它会记录典型事件，例如：

- `UserPromptSubmit`
- `LLMStart`
- `LLMStop`
- `ToolUse`
- `PostToolUse`
- `Stop`
- `Compact`
- `ErrorRecovery`

并通过 `on_event` 回调把事件推给上层。

### 6.2 AutonomousChatAgentService 怎么接到 Loop 上

`backend/app/gwy/services/autonomous_chat_agent_service.py` 是当前“自主 Agent”主入口之一。

它的工作方式是：

1. 组装上下文
2. 构建 tool registry
3. 初始化 `AgentRuntime`
4. 注入 `CLEAN_AUTONOMOUS_AGENT_SYSTEM_PROMPT`
5. 调用 `runtime.run()`
6. 收集 `state`、`trace`、`answer`
7. 兜底时走 deterministic fallback

系统提示词中已经明确写入了当前 Agent Loop 的策略：

- 先做计划
- 政策问答先 `search_policy_knowledge`，再 `compose_policy_answer`
- 岗位推荐先 `load_skill(position-planning)`，再结构化筛岗位
- 风险核验走 `review_position_risks`
- 复习规划走 `generate_study_plan`
- 必要时可以 `compact`

这意味着评测并不是在测一个“黑盒回答器”，而是在测一个可解释的 Agent Loop。

### 6.3 工具调用如何进入 trace

在 `autonomous_chat_agent_service.py` 里，政策问答链路已经把关键步骤拆成了可追踪的工具行为：

- `_tool_search_policy_knowledge()`
  - 记录 rewrite / retrieve / fuse_and_rerank / react_evidence_review 等阶段
  - 把 citations、rewritten_queries、rerank_results、metadata_filter 写回 state
  - 把 `policy_trace` 写回 state

- `_tool_compose_policy_answer()`
  - 如果没有 citations，会先补搜
  - 生成最终 answer
  - 把 `policy_answer` 和 `report` 写回 state

- `_tool_search_positions_pg()`
  - 调用 `PositionDecisionAgent`
  - 把 recommendations、summary、need_more_info、missing_fields 写回 state

- `_tool_review_position_risks()`
  - 调用 `RiskReviewAgent`
  - 把 `risk_review` 写回 state

- `_tool_generate_study_plan()`
  - 调用 `StudyPlanAgent`
  - 把 `study_plan` 和 `study_plan_markdown` 写回 state

- `_tool_compose_final_report()`
  - 调用 `ReportGeneratorAgent`
  - 组合最终 report

所以，Agent Loop 的“决策”在 runtime 中完成，而评测层通过 trace 和 state 来判断这个决策是否正确。

### 6.4 评测如何消费 Agent Loop 的输出

`backend/app/gwy/evals/adapters/agent_adapter.py` 是桥接层。

它把各种不同来源的输出统一成 `AgentObservation`，重点抽取：

- `trace`
- `tool_calls`
- `citations`
- `retrieved_documents`
- `memory_before`
- `memory_after`
- `returned_job_ids`
- `returned_jobs`
- `latency_ms`
- `input_tokens`
- `output_tokens`
- `estimated_cost`

这意味着评测不依赖某一个 Agent 的私有返回格式，而是尽量从 trace / state / metadata 中做归一化。

### 6.5 trace 完整性判断

`evaluate_online_observation()` 里有一个很实用的检查：`trace_complete`。

它会看 trace 是否到达终态事件，例如：

- `Stop`
- `done`
- `Finalize`
- 或者 `finalize` 且状态为 `done`

这部分是在线评测里很重要的“工程完整性”指标。

---

## 7. 现在前端看到了什么

当前 `frontend/src/routes/_layout/gwy/evals.tsx` 已经不只是一个摘要页了，而是一个可用的评测台。

它展示的层次是：

1. 数据集评测区
2. 左侧评测记录列表
3. 右侧评测报告
4. 当前 case 列表
5. 当前 case 的 observation
6. 当前 case 的 trace
7. run 级 scores
8. run 失败原因

也就是说，前端已经把“run / case / trace / scores / observation”分层展开了，不再只看一个薄 summary。

---

## 8. 当前对外可见的 API

评测路由已经挂到 `backend/app/api/routes/gwy_evals.py`，主要包括：

- `POST /gwy/evals/datasets/import-defaults`
- `GET /gwy/evals/datasets`
- `POST /gwy/evals/datasets`
- `GET /gwy/evals/runs`
- `POST /gwy/evals/datasets/{dataset_id}/runs`
- `POST /gwy/evals/runs`
- `GET /gwy/evals/runs/{run_id}`
- `GET /gwy/evals/runs/{run_id}/cases`

这套 API 足够支撑：

- 导入内置数据集
- 创建自定义数据集
- 运行数据集评测
- 记录在线评测
- 查看 run 详情
- 查看 case 级结果

---

## 9. 你前面提到的那些评测方向，现在覆盖到哪里了

| 方向 | 当前状态 | 说明 |
| --- | --- | --- |
| RAG 评测 | 已覆盖 | `rag` scorer 已支持召回、引用支持、答案点覆盖 |
| 高风险召回评测 | 部分覆盖 | 目前主要通过岗位硬约束 / forbidden job / constraint violation 体现，还不是独立“高风险召回” scorer |
| 工具调用评测 | 已覆盖 | `tool_call` scorer 已支持 required / forbidden / arguments / max calls |
| 多轮对话评测 | 部分覆盖 | Agent Loop 支持多轮与 trace，但还没有独立的 dialogue benchmark scorer |
| 长任务评测 | 部分覆盖 | runtime 支持 max_turns、compact、recovery，但未形成独立长任务基准集 |
| 端到端评测 | 已覆盖 | 在线评测 + 数据集评测都已经接入 |
| 大模型回答效果评测 | 部分覆盖 | `task_success` + `rag.answer_point_coverage` 能测一部分，但默认没有 LLM Judge |
| 工程评测 | 已覆盖一部分 | `efficiency` + `trace_complete` 已提供基础工程指标 |

如果把“覆盖”拆开看，当前已经比较扎实的是：

- 岗位结构化筛选
- 政策 RAG
- 工具调用纪律
- 记忆更新
- 基础工程指标

还没有完全独立成型的部分主要是：

- 多轮对话专项基准
- 长任务专项基准
- 更完整的回答质量审查
- 更独立的高风险召回 benchmark

---

## 10. 当前实现的边界和注意事项

### 10.1 默认不把 LLM Judge 当主评价器

这是为了保证第一版评测更稳定、可复现。当前主力还是确定性规则评分。

### 10.2 评测结果依赖 trace 质量

因为现在的评测要吃 trace、tool_calls、citations、memory_after 等结构化信息，所以 Agent Loop 的 trace 是否完整，会直接影响评测可用性。

### 10.3 数据集目前还是模板基准

内置数据集更多是项目级 smoke / regression / 基础 benchmark，不等于最终生产级金标集。

### 10.4 在线评测更接近真实场景，但 ground truth 不总是完整

在线评测目前更适合做“持续观察”和“回归跟踪”，不一定适合当作最严格的离线金标统计。

---

## 11. 后续最值得补的方向

如果继续往前走，最值得补的会是这几类：

1. 给“高风险召回”单独拆出一个 scorer。
2. 为多轮对话增加对话级指标，比如：
   - 是否正确追问
   - 是否保留上下文
   - 是否错误遗忘
3. 为长任务增加“阶段性目标完成度”指标。
4. 为回答质量增加可选 LLM Judge，但继续保留确定性指标做主基线。
5. 为工程评测增加更完整的运行画像，例如：
   - 每轮 tool 调用分布
   - 回退模型次数
   - compact 次数
   - error recovery 次数

---

## 12. 相关代码位置

- 评测数据模型：`backend/app/gwy/evals/schemas.py`
- 离线评测主入口：`backend/app/gwy/evals/run_eval.py`
- 在线评测与数据集服务：`backend/app/gwy/evals/service.py`
- 在线评测归一化：`backend/app/gwy/evals/adapters/agent_adapter.py`
- 评测 API：`backend/app/api/routes/gwy_evals.py`
- 通用 Agent Loop：`backend/app/gwy/agent_runtime/loop.py`
- 自主 Agent 入口：`backend/app/gwy/services/autonomous_chat_agent_service.py`
- 评测前端页面：`frontend/src/routes/_layout/gwy/evals.tsx`

---

## 13. 一句话总结

当前 GwyPilot 的 Agent 评测，已经从“只有一个分数”进化成了“能看 run、能看 case、能看 trace、能看 score、能看 observation”的可追踪评测系统；它和 Agent Loop 的结合点也已经明确：Agent Loop 负责产生可解释的过程信号，评测层负责把这些信号标准化、打分、落库、展示。
