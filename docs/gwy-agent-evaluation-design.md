# GwyPilot Agent 轻量评测功能设计文档

## 1. 目标

为 GwyPilot 当前 Agent 应用新增一套隔离的轻量级评测模块，用于验证 Agent 是否能够正确完成公务员岗位分析相关任务。

评测模块只服务于当前 Agent 应用，不做成独立 Agent 评测平台，不引入 Reviewer Agent、Evaluation Agent 或大型 Benchmark 框架。

评测重点回答以下问题：

- Agent 是否完成了用户任务。
- Agent 是否调用了正确工具。
- 工具参数是否正确。
- 岗位推荐是否违反学历、学位、专业、政治面貌、基层经历、应届身份、地区等硬约束。
- 政策问答是否检索到正确证据并给出有效引用。
- Memory 是否正确保存、更新和按需读取用户画像。
- 多 Agent 和 Memory 是否带来真实效果提升。
- 系统延迟、Agent 步数、工具调用次数、Token 和费用是多少。

## 2. 设计原则

- 不修改现有 Agent 主流程。
- 不影响现有 `/gwy` API、岗位推荐、政策 RAG、Memory、飞书推送等功能。
- 新增代码优先放在已有空包 `backend/app/gwy/evals/` 下。
- 评测模块通过 adapter 读取现有 Agent 输出和 trace。
- 岗位硬约束使用确定性代码评分，禁止交给 LLM Judge。
- LLM Judge 第一版默认关闭，只预留接口。
- 不伪造 ground truth，不编造政策答案或岗位结果。
- 测试失败时输出具体失败原因。
- Token、费用等无法获取时标记为 `unavailable`，不估算。
- Holdout 默认不在日常调试命令中运行。

## 3. 当前仓库可复用能力

### 3.1 Agent 入口

当前可作为评测入口的实现包括：

- `PolicyRagService.query_policy()`
- `PolicyRagService.answer_chat_message()`
- `AutonomousChatAgentService.run()`
- `PositionDecisionAgent.run()`
- `PositionSnapshotRuntimeService.run()`
- `PositionAnalysisService.execute_existing_task()`

### 3.2 Trace 来源

当前可复用的 trace 来源包括：

- `retrieval_trace`
- Agent Runtime 的 `trace`
- `GwyPositionAnalysisTask.trace_json`
- `GwyChatMessage.retrieval_trace`
- `GwyChatMessage.metadata_json`

### 3.3 岗位数据

岗位数据表为 `gwy_position`，主要字段包括：

- `id`
- `department_code`
- `department_name`
- `office_name`
- `job_title`
- `position_code`
- `major_requirement`
- `education_requirement`
- `degree_requirement`
- `political_status_requirement`
- `grassroots_years_requirement`
- `grassroots_project_experience`
- `work_location`
- `household_registration_location`
- `remarks`
- `source_file`
- `source_sheet`
- `source_row_number`
- `raw_data`

岗位推荐当前已经有 PostgreSQL 结构化筛选和规则评分逻辑，评测模块应复用这些事实数据，但不把 RAG 当作岗位筛选依据。

### 3.4 RAG 数据

政策数据来源包括：

- 原始政策 PDF
- `GwyPolicyDocument`
- Milvus chunk
- chunk debug 文件
- `citations`
- `rerank_results`

政策问答评测应优先检查 gold doc/chunk 是否进入 Top-K，以及引用是否来自正确文档。

### 3.5 Memory 数据

Memory 相关实现包括：

- `GwyUserProfile`
- `GwyConversationMemory`
- `GwyDecisionMemory`
- `GwyExperienceMemory`
- `AgentMemoryService`
- `LongTermMemoryService`
- `MemorySideQueryService`

当前 Memory 包含用户画像、会话工作记忆、长期岗位偏好和 side-query 按需加载能力。评测时不能只从最终回答猜测 Memory 是否正确，必须读取真实持久化结果或 Agent 返回的结构化状态。

## 4. 推荐目录结构

```text
backend/app/gwy/evals/
  README.md
  config.yaml
  schemas.py
  adapters/
    __init__.py
    agent_adapter.py
  scorers/
    __init__.py
    task_success.py
    tool_call.py
    job_constraint.py
    rag.py
    memory.py
    efficiency.py
  generators/
    generate_job_cases.py
    generate_policy_cases.py
  run_eval.py
  compare_experiments.py
  datasets/
    dev.jsonl
    holdout.jsonl
    templates/
  results/

backend/tests/gwy/evals/
  test_schemas.py
  test_tool_call_scorer.py
  test_job_constraint_scorer.py
  test_rag_scorer.py
  test_memory_scorer.py
  test_efficiency_scorer.py
  test_agent_adapter.py
  test_run_eval.py
```

## 5. 核心数据模型

### 5.1 EvalCase

统一测试样本格式：

```json
{
  "case_id": "job_001",
  "task_type": "job_filter",
  "split": "dev",
  "difficulty": "normal",
  "query": "我是计算机专业硕士，群众，想报四川岗位",
  "conversation": [],
  "initial_memory": {},
  "profile": {
    "education": "硕士研究生",
    "degree": "硕士",
    "major": "计算机科学与技术",
    "political_status": "群众",
    "target_regions": ["四川"]
  },
  "expected": {
    "job_ids": [],
    "forbidden_job_ids": [],
    "required_tools": [],
    "forbidden_tools": [],
    "tool_arguments": {},
    "gold_doc_ids": [],
    "gold_chunk_ids": [],
    "gold_answer_points": [],
    "memory_after": {},
    "should_ask_clarification": false,
    "report_required": false,
    "feishu_required": false
  },
  "metadata": {
    "data_source": "",
    "knowledge_version": "",
    "job_table_version": "",
    "notes": ""
  }
}
```

不是所有任务都必须填写所有字段。不同任务只填写可确定的 ground truth。

### 5.2 AgentObservation

adapter 统一后的 Agent 输出：

```json
{
  "final_answer": "",
  "status": "success",
  "returned_job_ids": [],
  "returned_jobs": [],
  "citations": [],
  "retrieved_documents": [],
  "tool_calls": [
    {
      "tool": "",
      "arguments": {},
      "success": true,
      "latency_ms": 0,
      "error": null
    }
  ],
  "memory_before": {},
  "memory_after": {},
  "agent_steps": 0,
  "latency_ms": 0,
  "input_tokens": null,
  "output_tokens": null,
  "estimated_cost": null,
  "trace": [],
  "raw_output": {}
}
```

## 6. Adapter 设计

`adapters/agent_adapter.py` 负责把不同 Agent 返回结构转为统一 `AgentObservation`。

第一版支持：

- 从 `answer` 或 `report` 提取 `final_answer`。
- 从 `recommendations` 提取 `returned_job_ids` 和 `returned_jobs`。
- 从 `citations` 提取引用。
- 从 `rerank_results` 提取检索文档。
- 从 `trace` 或 `retrieval_trace` 提取工具调用。
- 从 `metadata_json` 提取推荐结果、风险复核、飞书推送结果等。

adapter 不负责重新执行 Agent 逻辑，也不修正 Agent 结果。

如果缺少字段：

- Token 和费用标记为 `unavailable` 或 `null`。
- 没有标准工具调用字段时，只从现有 trace 尽力提取。
- 无法确认的能力在报告中标记为 `unavailable`。

## 7. Scorer 设计

### 7.1 Task Success Scorer

文件：`scorers/task_success.py`

职责：

- 判断最终状态是否符合预期。
- 判断是否需要追问。
- 判断是否生成最终报告。
- 判断最终回答是否为空。

输出指标：

- `task_success`

### 7.2 Tool Call Scorer

文件：`scorers/tool_call.py`

职责：

- 检查 required tools 是否被调用。
- 检查 forbidden tools 是否被调用。
- 检查工具调用次数是否超过上限。
- 检查工具参数字段是否正确。

输出指标：

- `required_tool_recall`
- `tool_precision`
- `tool_f1`
- `forbidden_tool_violation_rate`
- `argument_accuracy`

参数比较需要支持：

- 字符串标准化。
- 学历、学位同义归一，例如“硕士研究生”和“硕士”。
- 地区名称归一。
- 布尔值归一。
- 数字字符串归一。
- 列表和集合无序比较。
- 嵌套字段路径比较。

### 7.3 Job Constraint Scorer

文件：`scorers/job_constraint.py`

职责：

- 检查推荐岗位是否违反硬约束。
- 输出每个违规岗位的具体原因。

检查字段：

- 学历要求。
- 学位要求。
- 专业要求。
- 政治面貌要求。
- 基层工作经历。
- 服务基层项目经历。
- 应届毕业生限制。
- 地区要求。
- 用户明确排除岗位。

输出指标：

- `constraint_violation_rate`
- `job_precision`
- `job_recall`
- `job_f1`

失败详情格式：

```json
{
  "job_id": "",
  "field": "political_status_requirement",
  "user_value": "群众",
  "job_requirement": "中共党员",
  "reason": "政治面貌不满足"
}
```

该 scorer 禁止使用 LLM Judge。

### 7.4 RAG Scorer

文件：`scorers/rag.py`

职责：

- 检查 gold doc/chunk 是否进入 Top-K。
- 检查引用是否来自正确文档或 chunk。
- 检查回答是否覆盖人工标注的关键要点。

输出指标：

- `rag_recall_at_k`
- `citation_support_rate`
- `answer_point_coverage`

第一版不做严格字符串完全匹配，不要求回答和标准答案逐字一致。

### 7.5 Memory Scorer

文件：`scorers/memory.py`

职责：

- 检查用户画像字段是否正确保存。
- 检查字段更新是否覆盖旧值。
- 检查无关信息是否被错误保存。
- 检查不同用户之间是否串扰。
- 检查压缩后关键字段是否保留。

输出指标：

- `memory_field_accuracy`
- `memory_update_accuracy`
- `memory_leakage_count`
- `stale_field_usage_count`

Memory 评分必须读取真实持久化结果或结构化返回结果。

### 7.6 Efficiency Scorer

文件：`scorers/efficiency.py`

职责：

- 统计工具调用次数。
- 统计 Agent 步数。
- 统计平均延迟和 P95 延迟。
- 统计 Token 和费用。
- 统计失败率和重试次数。

无法获取的字段不估算。

## 8. Runner 设计

文件：`run_eval.py`

运行流程：

1. 读取 `config.yaml`。
2. 读取 JSONL 测试集。
3. 根据 split 选择 dev 或 holdout。
4. 对每条 case 调用指定 agent runner。
5. 使用 adapter 标准化输出。
6. 根据 task_type 调用 scorer。
7. 保存逐条结果。
8. 汇总指标。
9. 输出报告。

第一版 runner 支持三种模式：

- `offline`：读取已保存的 Agent 输出，只做评分。
- `service`：直接调用现有 Python service。
- `http`：调用本地 FastAPI API。

默认推荐先实现 `offline` 和 `service`，避免过早引入 API 鉴权和网络不稳定因素。

## 9. 输出文件

每次实验生成一个结果目录：

```text
backend/app/gwy/evals/results/<experiment_id>/
  results.jsonl
  summary.json
  summary.csv
  failures.jsonl
  report.md
  config.snapshot.yaml
```

### 9.1 results.jsonl

每条 case 的完整结果：

- case_id
- task_type
- raw_output
- normalized observation
- scores
- failure_reasons
- trace

### 9.2 summary.json

机器可读汇总：

- experiment_id
- git_commit
- dataset_version
- model
- prompt_version
- knowledge_version
- job_table_version
- case_count
- pass_count
- failed_count
- metrics

### 9.3 summary.csv

便于人工快速查看的指标表。

### 9.4 failures.jsonl

只保存失败 case，包括具体失败原因。

### 9.5 report.md

可直接放入项目文档的实验报告。

## 10. Dataset 设计

第一版目标 40 到 60 条。

推荐构成：

- 岗位筛选：20 条。
- 政策问答：15 条。
- 工具调用：10 条。
- Memory 多轮对话：10 条。
- 端到端业务流程：5 条。

如果某模块当前实现不完整，不强行生成对应正式样本，只保留人工标注模板。

数据划分：

- dev：约 45 条，用于日常调试。
- holdout：约 15 条，用于最终验证。

Holdout 不用于针对性修改 Prompt。

## 11. Dataset 生成器

### 11.1 岗位样本生成

文件：`generators/generate_job_cases.py`

数据来源：

- PostgreSQL `gwy_position` 表。

生成内容：

- 合格岗位 ID。
- 禁止推荐岗位 ID。
- 每个岗位通过或失败的具体字段。
- 用户缺失字段。

覆盖场景：

- 学历符合和不符合。
- 学位符合和不符合。
- 专业名称或专业代码边界。
- 政治面貌限制。
- 基层工作经历。
- 应届毕业生身份。
- 服务基层项目经历。
- 地区要求。
- 信息缺失需追问。
- 多条件同时存在。
- 条件冲突。
- 无符合岗位。

### 11.2 政策样本生成

文件：`generators/generate_policy_cases.py`

数据来源：

- 现有政策 PDF。
- chunk debug 文件。
- `GwyPolicyDocument`。
- Milvus 元数据。

生成内容：

- 问题。
- 正确文档 ID。
- 正确 chunk ID。
- 章节或证据片段。
- 标准答案要点。
- 文档年度和版本。
- 是否需要网页核验。

政策 ground truth 需要人工确认后才能进入正式 dev/holdout。

## 12. 对比实验

第一版只做两类对比。

### 12.1 单 Agent vs 多 Agent

前提：

- 如果当前系统支持两种模式，直接配置运行。
- 如果不支持，不为评测强行重构 Agent。

比较指标：

- 任务成功率。
- 工具调用 F1。
- 参数准确率。
- 岗位硬约束违规率。
- RAG Recall@5。
- 平均工具调用次数。
- P95 延迟。
- Token 消耗。

### 12.2 无 Memory vs 有 Memory

比较指标：

- 多轮任务成功率。
- 用户画像字段准确率。
- Memory 更新正确率。
- 用户重复提供信息次数。
- Token。
- 延迟。

## 13. 配置设计

示例：

```yaml
experiment_name: multi_agent_memory_v1
dataset_split: dev
model: actual-model-name
temperature: 0
prompt_version: actual-version
knowledge_version: actual-version
job_table_version: actual-version
top_k: 5
max_agent_steps: 10
enable_multi_agent: true
enable_memory: true
enable_web_verification: true
enable_llm_judge: false
mock_external_services: true
```

每次实验必须保存配置快照。

## 14. 外部服务 Mock 策略

需要 mock 的服务：

- 飞书 webhook。
- Web search。
- Web fetch。
- Playwright 网页读取。
- LLM chat completion。
- Embedding。
- Rerank。
- Milvus。

评测默认不真实发送飞书消息。

## 15. 单元测试计划

必须覆盖：

- `EvalCase` schema validation。
- JSONL 加载失败时输出行号。
- 工具 required / forbidden / argument scoring。
- 参数标准化。
- 岗位硬约束违规识别。
- RAG recall@k。
- citation support。
- Memory field accuracy。
- runner 输出所有结果文件。
- adapter 从现有 trace 提取工具调用。

## 16. 集成测试计划

第一版集成测试使用：

- SQLite 临时库。
- 人工构造少量 `GwyPosition`。
- fake Agent runner。
- fake LLM。
- fake Milvus。
- fake Feishu。

不连接生产数据库，不修改真实数据。

## 17. 当前缺口

当前代码中评测需要适配或补充的缺口：

- Agent 输出没有统一 `AgentObservation`。
- 部分 trace 不是标准工具调用结构。
- token 和 cost 未统一记录。
- retry count 未统一记录。
- Memory before/after 不是所有入口都返回。
- citation 是否真正支持答案仍需要人工证据或规则判断。
- 专业目录语义匹配尚不完整，不应声称已经完整覆盖。

## 18. 实施顺序

建议按以下顺序实施：

1. 实现 schema 和 JSONL 加载。
2. 实现 adapter，只读现有 Agent 输出。
3. 实现 tool call scorer。
4. 实现 job constraint scorer。
5. 实现 RAG scorer。
6. 实现 Memory scorer。
7. 实现 efficiency scorer。
8. 实现 offline runner。
9. 实现 service runner。
10. 实现结果导出。
11. 实现岗位样本生成器。
12. 实现政策样本模板生成器。
13. 编写 README。
14. 跑 dev 小集，输出真实 report。

## 19. 不做的事情

第一版明确不做：

- 不做独立评测平台。
- 不做 Evaluation Agent。
- 不做大型 Benchmark 系统。
- 不用 LLM Judge 判断岗位硬约束。
- 不伪造政策标准答案。
- 不伪造提升百分比。
- 不重构现有 Agent Runtime。
- 不默认运行 holdout。
- 不真实重复发送飞书消息。

