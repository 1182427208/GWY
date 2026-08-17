# GwyPilot Agent Eval 评测系统优化方案

> 目标：在保留现有 **Run / Case / Trace / Score / Failure Reason** 评测底座的基础上，将当前偏“运行记录展示”的评测页面，升级为能够真正判断 Agent 是否做对、为什么做对、哪里做错，以及新版本是否优于旧版本的 Agent Eval 系统。

---

# 1. 当前评测系统现状

当前评测页面已经具备较完整的基础骨架：

```text
Run
→ Case
→ Score
→ Trace
→ Failure Reason
```

已经能够展示：

- Run 状态；
- Case 列表；
- Trace 是否完整；
- Trace Steps；
- Task Success；
- Efficiency；
- Tool Call Count；
- Agent Steps；
- Latency；
- Failure Reasons。

这个底座本身是有价值的，不建议推翻。

当前真正的问题在于：

> **评测系统主要在回答“Agent 有没有跑完”，还没有充分回答“Agent 做得对不对”。**

---

# 2. 当前最核心的问题

## 2.1 E2E Case 的 Scorer 太少

当前一个完整 E2E Case 往往只运行：

```text
task_success
efficiency
```

以“查询某个具体岗位报录比”为例，实际执行链路应该至少涉及：

```text
岗位识别
→ 岗位数据查询
→ 是否需要外部检索
→ 报名人数 / 招录人数获取
→ 岗位代码 / 年份核验
→ 报录比计算
→ 来源验证
→ 最终回答
```

但当前主要检查：

```text
有没有正常结束
用了多少工具
耗时多久
```

因此即使出现以下问题，也可能被判定为 `passed`：

- 查错岗位；
- 查错年份；
- 查到其他部门同名岗位；
- 报录比来源不可靠；
- 最终答案中的数字没有 Evidence；
- Tool 被权限阻断但 Agent 仍自行给出结果；
- Browser 失败后仍生成缺少依据的自然语言答案。

这说明：

> `task_success` 当前语义过粗，需要和业务验证及关键 Scorer 结合。

---

# 3. 评测系统总体改造目标

新的 Agent Eval 建议采用：

```text
Critical Gate
+
Multi-dimensional Score
+
Trace-based Analysis
```

整体评测分为：

```text
Layer 1：Task / Business Correctness
Layer 2：Execution / Tool Correctness
Layer 3：Evidence / Groundedness
Layer 4：Final Answer Quality
Layer 5：Engineering Efficiency
```

最终状态不再简单等于：

```text
有回答 + Trace Complete = PASS
```

而应该是：

```text
Critical Gate PASS
+
Quality Score 达标
=
PASS
```

---

# 4. 第一层：Task / Business Correctness

这一层回答：

> **Agent 最终做的事情是不是用户真正要求的事情？**

例如用户：

```text
法务管理岗位一级主任科员及以下，就是这个岗位，看看报录比。
```

首先必须确认：

```text
到底查的是不是用户指定的那个岗位。
```

---

# 5. 新增 Position Identity Scorer

建议新增：

```text
position_identity
```

它专门判断：

- 岗位名称；
- 部门；
- 岗位代码；
- 招录年份；

是否与用户指定对象一致。

## 5.1 ExpectedOutcome

建议为相关 Case 增加：

```json
{
  "expected_position": {
    "department": "目标部门",
    "position_name": "法务管理岗位一级主任科员及以下",
    "position_code": "岗位代码",
    "year": 2026
  }
}
```

Observation 中对应保存：

```json
{
  "resolved_position": {
    "department": "...",
    "position_name": "...",
    "position_code": "...",
    "year": 2026
  }
}
```

## 5.2 推荐指标

```text
position_name_match
department_match
position_code_match
year_match
position_identity_accuracy
```

优先级建议：

```text
position_code
>
department
>
position_name
```

因为“一级主任科员及以下”这类岗位名称可能大量重复，真正稳定的唯一标识应该是岗位代码 + 部门 + 年份。

---

# 6. Job Constraint Scorer 继续作为核心指标

现有岗位硬约束评测应该继续保留并提升优先级。

重点检查：

```text
学历
学位
专业
政治面貌
基层经历
应届身份
资格证书
地区限制
```

例如：

```text
用户不是党员
→ 推荐“仅限中共党员”岗位
```

应该直接认定为：

```text
Critical Failure
```

建议继续使用：

```text
constraint_violation_rate
job_precision
job_recall
job_f1
```

---

# 7. 第二层：Execution / Tool Correctness

这一层回答：

> **Agent 在执行过程中是不是用了正确的方法完成任务？**

重点评：

```text
Tool Selection
Tool Arguments
Tool Sequence
Tool Role Compliance
Retry
Error Recovery
```

---

# 8. Tool Call Scorer 升级

现有 Tool Call Scorer 可以继续使用：

```text
required_tool_recall
tool_precision
tool_f1
forbidden_tool_violation_rate
argument_accuracy
```

建议额外增加：

```text
role_tool_violation
duplicate_tool_call_rate
unrecovered_tool_error
tool_fallback_success
```

---

# 9. Agent Role Tool Compliance

重构后的 Agent 建议收敛为：

```text
PositionAgent
EvidenceAgent
AnalysisAgent
```

那么评测应该检查 Agent 是否遵守职责边界。

例如：

```text
PositionAgent
允许：
PostgreSQL

禁止：
Browser
Web Search
```

```text
EvidenceAgent
允许：
Milvus
Search
Fetch
Browser
```

```text
AnalysisAgent
默认：
只消费已有 Evidence
不直接 Browser
```

因此：

```text
PositionAgent → web_browser
```

虽然 Tool 本身可能存在，也应该记为：

```text
role_tool_violation
```

---

# 10. Duplicate Tool Call 评测

ReAct Agent 很容易产生重复搜索。

例如：

```text
Search["2026 法务管理岗位 报录比"]
Search["2026 法务管理岗位 报录比"]
Search["2026 法务管理岗位 报录比"]
```

如果参数几乎一致且 Observation 没有新增信息：

```text
duplicate_tool_call_rate ↑
```

建议记录：

```text
tool_name
arguments_hash
observation_hash / summary
```

---

# 11. Tool Error Recovery

需要区分：

```text
Tool Error
```

和：

```text
Unrecovered Tool Error
```

例如：

```text
Fetch 失败
→ Playwright 成功
```

属于：

```text
recovery_success
```

而：

```text
Browser permission blocked
→ 没有取得报录比
→ Agent 仍然给出一个具体数值
```

应该是：

```text
Critical Failure
```

---

# 12. 第三层：Evidence / Groundedness

这一层需要回答：

> **Agent 最后的事实性结论有没有真实证据支撑？**

---

# 13. Evidence 统一结构化

建议所有 PostgreSQL、Milvus、Web、PDF、Browser 结果最后都进入统一 Evidence Store。

每条 Evidence 至少包含：

```json
{
  "evidence_id": "ev_001",
  "claim_type": "registration_count",
  "value": 138,
  "source_url": "...",
  "source_title": "...",
  "source_type": "official",
  "year": 2026,
  "position_code": "...",
  "retrieved_at": "...",
  "confidence": 0.95
}
```

---

# 14. 新增 Evidence Quality Scorer

推荐增加：

```text
evidence_coverage
source_authority
evidence_freshness
evidence_position_match
evidence_year_match
evidence_conflict_rate
```

## 14.1 Evidence Coverage

例如：

```text
报名人数：138       ✅
招录人数：2         ✅
报录比：69:1        ✅
进面分数：132.5     ❌
```

则：

```text
evidence_coverage = 0.75
```

---

# 15. Source Authority

尤其报录比、进面分数、政策类信息，应区分来源可靠性。

建议：

```text
Level A
官方公务员招录网站
招录单位官网
官方公告 / PDF

Level B
政府媒体
官方公众号

Level C
大型考试信息平台

Level D
论坛
博客
用户分享
```

对应：

```text
source_authority_score
```

如果只有 Level C / D：

```text
最终回答必须标记“非官方来源，仅供参考”
```

---

# 16. 新增 Claim Groundedness Scorer

这个指标判断：

> 最终答案里的每一个事实性 Claim 是否可以回溯到 Evidence。

例如回答：

```text
该岗位招录 2 人，
报名 138 人，
报录比约 69:1，
竞争强度中等。
```

拆成：

```text
Claim 1：招录 2 人
Claim 2：报名 138 人
Claim 3：报录比 69:1
Claim 4：竞争强度中等
```

分别检查：

```text
Claim 1 → PostgreSQL Evidence
Claim 2 → Web Evidence
Claim 3 → 138 / 2
Claim 4 → Analysis Rule
```

最终计算：

```text
claim_groundedness
unsupported_claim_rate
```

---

# 17. 禁止“无证据预测”

例如 Agent 输出：

```text
预计今年进面分数会上涨 5 分。
```

但没有：

```text
历史趋势模型
明确证据
规则依据
```

应计为：

```text
unsupported_claim
```

---

# 18. 第四层：Final Answer Quality

确定性指标可以评：

```text
是否返回报录比
是否包含年份
是否包含岗位名称
是否包含来源
是否说明不确定性
```

而：

```text
清晰度
可读性
完整性
决策价值
风险解释质量
```

更适合增加可选 LLM Judge。

---

# 19. LLM Judge 的定位

建议仅做：

```text
Correctness
Completeness
Groundedness
Usefulness
Clarity
```

每项：

```text
1 ~ 5
```

返回：

```json
{
  "correctness": 5,
  "completeness": 4,
  "groundedness": 5,
  "usefulness": 4,
  "clarity": 5,
  "critical_issue": null
}
```

但 LLM Judge 不能替代：

```text
岗位代码
工具参数
硬约束
Evidence ID
```

这类确定性检查。

推荐：

```text
Deterministic Scorer = 主基线
LLM Judge = 主观补充
```

---

# 20. 第五层：Engineering Efficiency

当前已有：

```text
tool_call_count
agent_steps
latency_ms
input_tokens
output_tokens
estimated_cost
```

继续保留。

但 UI 上不建议：

```text
efficiency
passed = true
```

因为“效率”不是简单二元正确错误。

建议改成：

```text
within_budget
efficiency_grade
```

---

# 21. Efficiency 建议展示

```text
Agent Turns
LLM Calls
Tool Calls
Trace Events
Reflection Rounds
Replans
Latency
Tokens
Cost
```

例如：

```text
Agent Turns          10
LLM Calls             6
Tool Calls            5
Trace Events          35
Reflection Rounds      1
Replans                0
Latency               33.9s
```

---

# 22. 明确 Agent Steps 和 Trace Steps

当前：

```text
agent_steps = 10
trace_steps = 35
```

容易混淆。

建议 UI 统一改名：

```text
Agent Turns
Trace Events
Tool Calls
LLM Calls
Reflection Rounds
Replans
```

---

# 23. Latency Breakdown

当前只有：

```text
latency_ms = 33938
```

无法分析瓶颈。

建议聚合：

```text
LLM Latency
PostgreSQL Latency
Milvus Latency
Search Latency
Fetch Latency
Browser Latency
Reflection Latency
Validation Latency
```

例如：

```text
Total        33.9s
LLM          18.2s
PostgreSQL    1.1s
Milvus        0.7s
Search        3.5s
Fetch         2.1s
Other         8.3s
```

---

# 24. Token 数据必须补齐

当前：

```text
input_tokens = 不可用
output_tokens = 不可用
estimated_cost = 不可用
```

建议优先修复。

每次 Model Call 都记录：

```json
{
  "model": "...",
  "input_tokens": 3800,
  "output_tokens": 520,
  "latency_ms": 4300
}
```

聚合：

```text
Total Input Tokens
Total Output Tokens
Cached Tokens
Reasoning Tokens（如果模型提供）
Estimated Cost
```

这样后续才能公平比较：

```text
旧 Agent
vs
ReAct + Reflection
```

---

# 25. Task Success 必须重新定义

不建议继续：

```text
Loop Stop
+
Answer Exists
=
Task Success
```

建议：

```text
Task Success
=
Runtime Completed
AND
Business Validation Passed
AND
Critical Metrics Passed
```

---

# 26. 建议任务状态

```text
PASS
PASS_WITH_WARNING
PARTIAL
FAIL
BLOCKED
```

## PASS

```text
关键任务完成
证据充分
Critical Metric 全部通过
```

## PASS_WITH_WARNING

例如：

```text
找到了报录比
但仅有第三方来源
```

## PARTIAL

例如：

```text
岗位确认完成
报名人数无法获得
```

## BLOCKED

例如：

```text
Browser Permission Blocked
```

## FAIL

例如：

```text
查错岗位
编造报录比
违反硬约束
```

---

# 27. Critical Metric 机制

不是所有指标都应该权重相同。

## Critical

失败直接导致 Case FAIL：

```text
wrong_position
hard_constraint_violation
fabricated_evidence
forbidden_tool_violation
unrecovered_critical_tool_error
artifact_invalid
```

## Quality

影响分数：

```text
answer_completeness
source_authority
claim_groundedness
answer_clarity
```

## Efficiency

主要观察：

```text
latency
tokens
tool_calls
agent_turns
```

---

# 28. Passed 建议改为“Gate + Score”

例如：

```text
Critical Gate：PASS
Quality Score：86 / 100
```

则：

```text
PASS
```

如果：

```text
Quality Score：93
```

但：

```text
wrong_position = true
```

仍然：

```text
FAIL
```

---

# 29. 推荐评分权重示例

对于“岗位报录比查询”：

```text
Task Completion       20%
Position Identity     20%
Tool Correctness      10%
Evidence Quality      20%
Claim Groundedness    15%
Answer Quality        10%
Efficiency             5%
```

但 Critical Metric 单独 Gate，不参与“高分抵消”。

---

# 30. 为不同任务定义 Eval Profile

建议不要只依赖：

```text
task_type = e2e
```

而增加：

```text
eval_profile
```

## 岗位筛选

```text
job_filter
```

Scorers：

```text
task_success
job_constraint
position_identity
tool_call
efficiency
```

## 政策问答

```text
policy_qa
```

Scorers：

```text
task_success
rag
citation_support
claim_groundedness
answer_quality
efficiency
```

## 岗位外部信息查询

例如：

```text
报录比
进面分数
报名人数
```

Profile：

```text
position_research
```

Scorers：

```text
task_success
position_identity
tool_call
evidence_quality
claim_groundedness
answer_quality
efficiency
```

## 完整岗位分析报告

```text
position_analysis_e2e
```

Scorers：

```text
planner
task_success
position_identity
job_constraint
tool_call
evidence_quality
analysis
report_artifact
efficiency
```

## 复习规划

```text
study_plan
```

Scorers：

```text
task_success
study_plan_consistency
study_plan_coverage
feasibility
answer_quality
efficiency
```

---

# 31. Planner Eval

Main Agent 采用 Plan-and-Execute 后，应单独评估 Planner。

推荐指标：

```text
plan_goal_coverage
todo_redundancy_rate
dependency_accuracy
agent_route_accuracy
invalid_todo_rate
replan_success_rate
```

例如用户要求：

```text
筛岗位
+
查竞争
+
做复习规划
```

Planner 只生成：

```text
岗位筛选
竞争分析
```

漏掉复习规划，则：

```text
plan_goal_coverage < 1
```

---

# 32. Execution Quality 模块

建议评测页新增：

```text
Execution Quality
```

展示：

```text
Planning
✓ Todo generated
✓ User objectives covered
✓ No duplicated Todo

Routing
✓ Position → PositionAgent
✓ Evidence → EvidenceAgent

Tool Usage
✓ Required tools used
✓ No forbidden tools
✓ No repeated calls

Recovery
✓ No unrecovered error

Reflection
✓ Reflection performed
✓ Candidate accepted

Validation
✓ Completion criteria passed
```

这能直接回答：

> “Agent 的执行过程是不是正确？”

---

# 33. Reflection 也需要评测

不是“用了 Reflection”就一定好。

建议增加：

```text
reflection_trigger_count
reflection_repair_success_rate
false_repair_rate
average_reflection_rounds
```

## Repair Success

```text
第一次结果错误
→ Reflection 找到问题
→ 第二次结果正确
```

记：

```text
reflection_repair_success
```

## False Repair

```text
第一次本来正确
→ Reflection 错误修改
→ 第二次变差
```

记：

```text
false_repair
```

这样才能证明 Reflection 有没有带来净收益。

---

# 34. Trace 事件进一步标准化

建议新 Agent Loop 输出统一事件：

```text
UserPromptSubmit
PlanCreated
TaskCreated
TaskStarted
AgentRouted
LLMStart
LLMStop
ToolUse
ToolResult
ReflectionStart
ReflectionResult
ValidationStart
ValidationResult
TaskCompleted
ArtifactCreated
ArtifactValidated
Compact
ErrorRecovery
Stop
```

---

# 35. Failure Taxonomy

当前：

```text
failure_reasons
```

建议进一步结构化。

分类：

```text
PLAN_ERROR
ROUTING_ERROR
WRONG_POSITION
CONSTRAINT_VIOLATION
TOOL_ARGUMENT_ERROR
TOOL_PERMISSION_BLOCKED
TOOL_NOT_REGISTERED
TOOL_TIMEOUT
RETRIEVAL_MISS
EVIDENCE_CONFLICT
UNSUPPORTED_CLAIM
HALLUCINATION
REFLECTION_FAILURE
VALIDATION_FAILURE
MEMORY_ERROR
ARTIFACT_INVALID
TIMEOUT
```

---

# 36. Case 页面 UI 优化

当前 Case 详情偏工程字段：

```text
case_id
passed
trace_steps
```

建议改成：

```text
Query
Expected Goal
Resolved Position
Final Result
Evidence
Status
```

例如：

```text
Query
法务管理岗位一级主任科员及以下，就是这个岗位，看看报录比

Expected Goal
查询指定岗位报名竞争情况

Resolved Position
岗位：法务管理岗位一级主任科员及以下
岗位代码：xxxx
年份：2026

Final Result
报名人数：138
招录人数：2
报录比：69:1

Evidence
官方岗位表
官方报名统计

Status
PASS
```

---

# 37. Score Card 不再只显示 Passed

当前：

```text
task_success

passed = true
failure_reasons = 0
success = 1
```

信息不足。

建议：

```text
Task Success                          PASS

✓ Final answer generated
✓ Requested position resolved
✓ Required data returned
✓ Evidence exists
✓ No unrecovered critical error
✓ Completion criteria satisfied
```

失败则：

```text
Task Success                          FAIL

✓ Final answer generated
✗ Position code mismatch
✓ Trace complete
```

---

# 38. Run 页面 UI 优化

Run 顶部：

```text
Evaluation Report

PASS                      Overall Score 86 / 100
Cases                     1 / 1 Passed
Critical Failures         0
Trace Complete            true
Total Latency             33.9s
```

---

# 39. Quality Overview

建议增加：

```text
Task Completion       100
Position Identity     100
Tool Correctness       90
Evidence Quality       82
Groundedness           88
Answer Quality         85
Efficiency             67
```

---

# 40. Run Scores 应该是聚合，不要重复 Case

当前一个 Case 时：

```text
Case Scores
task_success
efficiency

Run Scores
task_success
efficiency
```

完全重复。

Run 层未来应该聚合：

```text
Task Success Rate
Position Accuracy
Tool F1
Constraint Violation Rate
RAG Recall@K
Citation Support
Groundedness
P50 Latency
P95 Latency
Average Tool Calls
Average Agent Turns
```

---

# 41. Raw JSON 和 Trace 默认折叠

当前大量 JSON 直接显示在主界面。

建议：

```text
主界面
=
Quality Dashboard
```

而：

```text
Raw Observation
Raw JSON
Trace Events
```

放到：

```text
Advanced / Debug
```

默认折叠。

---

# 42. 在线评测和离线评测职责

## 在线评测

负责：

```text
真实运行持续观察
Trace 记录
失败 Case 收集
质量趋势
线上异常
```

不建议每次都做昂贵 LLM Judge。

推荐：

```text
确定性 Scorer
+
抽样 Judge
```

## 离线评测

负责：

```text
Prompt Regression
模型切换
Tool 改造
Agent Loop 重构
ReAct / Reflection 改造
版本上线验证
```

这次重构必须做：

```text
Before
vs
After
```

---

# 43. 建议离线数据集拆分

```text
datasets/
├── planner/
├── job_filter/
├── position_identity/
├── policy_rag/
├── position_research/
├── evidence/
├── memory/
├── long_task/
├── report/
└── study_plan/
```

---

# 44. 重构前后应该对比什么

建议固定一套 Regression Dashboard：

| Metric | Old | New |
| --- | ---: | ---: |
| End-to-End Success Rate | | |
| Position Identity Accuracy | | |
| Job Constraint Violation | | |
| Tool F1 | | |
| Forbidden Tool Violation | | |
| Evidence Coverage | | |
| Claim Groundedness | | |
| RAG Recall@K | | |
| Citation Support | | |
| Avg Agent Turns | | |
| Avg Tool Calls | | |
| P50 Latency | | |
| P95 Latency | | |
| Input Tokens | | |
| Output Tokens | | |
| Reflection Repair Rate | | |
| Unrecovered Error Rate | | |

这样才能证明：

> 新 Agent 架构不仅“更优雅”，而且任务成功率、事实可靠性、工具使用和工程效率都有量化变化。

---

# 45. 推荐的实现优先级

## Priority 1：重构 Task Success

先解决：

```text
有答案 ≠ 任务成功
```

接入：

```text
Validation Gate
Critical Metric
```

## Priority 2：E2E 动态 Scorer

针对当前“报录比查询”至少加入：

```text
position_identity
tool_call
evidence_quality
claim_groundedness
```

## Priority 3：Evidence Schema

统一：

```text
PostgreSQL
Milvus
Web
Browser
PDF
```

输出为 Evidence。

## Priority 4：补 Token / Model Call 数据

否则无法比较：

```text
旧 Agent
vs
ReAct + Reflection
```

真实成本。

## Priority 5：优化 Eval UI

从：

```text
JSON Viewer
```

升级成：

```text
Quality Dashboard
+
Debug Drill-down
```

---

# 46. 推荐最终 Eval 页面结构

```text
Evaluation Report
│
├── Overall
│   ├── PASS / FAIL
│   ├── Overall Score
│   ├── Critical Failures
│   └── Cases Passed
│
├── Quality Overview
│   ├── Task
│   ├── Position
│   ├── Tool
│   ├── Evidence
│   ├── Groundedness
│   ├── Answer
│   └── Efficiency
│
├── Case List
│
├── Case Detail
│   ├── Query
│   ├── Expected Goal
│   ├── Resolved Position
│   ├── Final Result
│   └── Evidence
│
├── Execution Quality
│   ├── Plan
│   ├── Routing
│   ├── Tools
│   ├── Reflection
│   └── Validation
│
├── Scores
│
├── Failure Analysis
│
├── Efficiency
│   ├── Agent Turns
│   ├── LLM Calls
│   ├── Tool Calls
│   ├── Latency
│   └── Tokens
│
└── Debug
    ├── Trace
    ├── Observation
    └── Raw JSON
```

---

# 47. 面试时如何解释这套 Agent Eval

推荐回答：

> 我不会只看 Agent 最后的自然语言回答，而是把评测拆成多层。第一层看业务结果，例如岗位是否识别正确、是否违反专业学历等硬约束；第二层看 Agent 的执行轨迹，通过 Trace 验证工具选择、参数、调用次数和错误恢复是否正确；第三层看 Evidence 和 Groundedness，确保政策、报录比、进面分数等事实都有可回溯证据；第四层再评最终回答的完整性和可读性。同时记录 Agent Steps、Tool Calls、Latency、Token 和 Cost 做工程效率评测。硬约束、岗位代码和 Tool 参数尽量使用确定性 Scorer，主观回答质量再使用可选的 LLM Judge。离线用金标数据集做版本 Regression，线上持续记录真实 Trace 和失败 Case，因此可以判断 Agent 不只是“回答看起来正确”，而是从执行过程到最终结果都有可验证性。

如果继续追问 Reflection：

> Reflection 是 Agent 内部的自我纠错机制，而 Evaluation 是 Agent 外部的质量判断。Reflection 可以提高单次任务成功率，但不能作为客观正确性的唯一依据，所以系统仍然需要基于金标、业务规则、工具轨迹和 Evidence 的独立评测。

---

# 48. 最终目标

当前评测系统已经能够回答：

```text
Agent 跑了什么？
```

下一阶段应该升级到能够回答：

```text
Agent 为什么这么做？
↓
它做的是不是正确的？
↓
查的是不是用户真正指定的对象？
↓
使用的 Tool 是否合理？
↓
事实有没有 Evidence？
↓
有没有幻觉或无依据结论？
↓
执行过程中哪里失败？
↓
新版本相比旧版本有没有真正变好？
```

最终形成：

```text
Trace
+
Business Validation
+
Tool Evaluation
+
Evidence Evaluation
+
Answer Evaluation
+
Efficiency Evaluation
+
Regression Dataset
```

这样 GwyPilot 的评测模块才真正从“运行记录页面”升级为完整的 **Agent Evaluation & Observability System**。
