# GwyPilot Agent Loop 重构优化方案 V2
## —— 融合 Plan-and-Execute、ReAct、Reflection、运行时验证、自动化评测、报告与复习规划

> **核心目标**
>
> 在不推翻现有 GwyPilot 总体架构、不重做现有 Tool Registry、MCP、权限控制、异常处理、Memory 和评测基础设施的前提下，对当前 Agent Harness 做一次“收敛式重构”：
>
> - **主 Agent：Plan-and-Execute / Plan-and-Solve**，负责全局目标理解、任务拆解、调度、Replan 和最终综合；
> - **固定少量子 Agent：ReAct + Reflection**，负责单域任务中的动态工具选择、事实获取、局部推理和完成前自校验；
> - **Validation Gate：确定性运行时验证**，判断任务是否真的达到 completion criteria，不依赖 Agent 自己说“完成了”；
> - **Eval Layer：沿用当前已有的轻量评测系统**，基于 trace / state / observation 做在线评测、离线数据集评测和回归；
> - **Artifact Layer：报告和复习规划不再是随意生成的一段文本，而是有 Schema、有验证、有来源、有可执行粒度的产品结果。**
>
> 整体可以概括为：
>
> **Global Plan + Local ReAct + Reflection + Deterministic Verification + Trace-based Evaluation + Structured Artifacts**

---

# 1. 先明确：现在真正需要解决的不是“Agent 不够多”，而是系统缺少收敛

当前系统已经具备很多正确的基础设施：

```text
Agent Runtime / Agent Loop
TodoWrite
Tool Registry
MCP Tool Calling
Permission Check
Timeout / Retry / Error Recovery
Context Compact
Memory Side Query
PostgreSQL
Milvus
Policy RAG
Position Analysis
Study Plan
Report Generation
Trace
Online Eval
Offline Dataset Eval
```

因此问题不是“要不要重新造一个 Agent 平台”，而是以下几个层面没有很好地闭环。

## 1.1 子 Agent 太多、职责粒度过细

当前容易形成：

```text
岗位筛选 Agent
政策检索 Agent
政策回答 Agent
风险核验 Agent
报告 Agent
复习计划 Agent
网页 Agent
……
```

部分“Agent”实际上只是：

- 一个 Tool Wrapper；
- 一个固定 Workflow；
- 一个输出格式转换器；
- 一个 Skill 本应承担的领域规则。

最终结果就是：

> **一个业务动作 ≈ 一个 Agent。**

这会导致：

- Agent 数量不断膨胀；
- 上下文重复；
- 多个 Agent 同时具有相似工具；
- 责任边界不清；
- 很难判断错误发生在哪一层；
- 自动评测难以对不同 Agent 做稳定比较。

---

## 1.2 子 Agent 内部过于 Workflow 化

现在部分能力本质上仍然接近：

```text
步骤 A
→ 步骤 B
→ 步骤 C
→ 固定工具
→ 固定输出
```

这类路径适合确定性业务流程，但不适合：

```text
“这个岗位专业要求是否真的匹配？”
“现有政策证据够不够？”
“是否需要联网？”
“Fetch 结果不完整，要不要再用浏览器？”
“两个来源冲突，该继续检索还是返回不确定？”
```

这些任务需要：

> **根据 Observation 动态决定下一步 Action。**

因此子 Agent 应该从固定步骤执行器，变成受 Task Contract 和 Tool Allowlist 约束的 **ReAct 执行单元**。

---

## 1.3 “Agent 说完成”不等于任务真的完成

这是当前最需要补的一层。

当前截图已经出现了典型问题：

```text
compose_snapshot_report is not registered in the web agent runtime
compose_snapshot_report was blocked by permissions
```

但外层任务状态仍显示：

```text
completed
```

这说明目前：

> **运行状态完成 != 业务任务完成。**

如果工具失败、权限阻断、报告没有真正生成，但 Agent 最终停止了 Loop，就被当成 completed，这对后续评测和产品体验都有很大问题。

必须加入：

```text
Agent Finish
   ≠
Task Completed
```

而应该是：

```text
Agent 产生 Candidate Result
        ↓
Reflection
        ↓
Runtime Validation Gate
        ↓
满足 Completion Criteria？
   ├─ Yes → COMPLETED
   ├─ Partial → PARTIAL
   └─ No → RETRY / REPLAN / FAILED
```

---

## 1.4 当前评测已经有基础，但没有真正成为 Agent Harness 的“质量闭环”

根据当前项目已有实现，GwyPilot 已经拥有一套比较完整的轻量评测能力：

```text
EvalCase
ExpectedOutcome
AgentObservation
ScoreBundle
CaseResult
EvalConfig

在线评测
离线 Dataset Eval
Trace
Tool Calls
RAG
Job Constraints
Memory
Efficiency
```

这部分不应该推翻。

真正应该做的是：

> **让新 Agent Loop 的 Task Contract、SubAgentResult、Trace、Evidence、Artifact 都天然成为评测输入。**

也就是说，重构时不是最后“再接一个评测模块”，而应该从数据协议层就考虑：

```text
这一步能不能被验证？
这次工具调用能不能被评测？
这个最终结论有没有 evidence id？
这个报告是否可以做确定性检查？
这个复习计划是否满足时间约束？
```

---

## 1.5 当前报告和复习规划是“生成出来了”，但不是“可用产品”

截图中目前的结果暴露出两个问题。

### 报告问题

当前“报告正文”里混入了：

- 内部 tool 名称；
- runtime trace；
- compact 事件；
- 未注册工具报错；
- 权限错误；
- 原始推荐查询文本；
- 大段没有结构的筛选信息。

这实际上更接近：

> **调试页面 / Trace Viewer**

而不是用户最终应该阅读的“岗位分析报告”。

### 复习规划问题

截图中：

```text
总周数：16周
每日学习时长：8小时
申论：448小时
行测：448小时
```

如果 16 周 × 7 天 × 8 小时：

```text
总时间 = 896 小时
```

两个科目各 448 小时确实正好分完。

但阶段安排又是：

```text
第1-5周：4小时/天
第6-10周：6小时/天
第11-16周：8小时/天
```

按每天都学习计算：

```text
5 × 7 × 4 = 140
5 × 7 × 6 = 210
6 × 7 × 8 = 336

阶段总时长 = 686 小时
```

与顶部：

```text
896 小时
```

明显不一致。

另外：

```text
“申论 50%”
“行测 50%”
```

没有体现：

- 用户真实基础；
- 弱项；
- 岗位目标分数；
- 模考结果；
- 时间距离；
- 动态调整；
- 每周可验收成果。

所以现在的 Study Plan 是：

> **看起来像计划，但实际上是静态模板。**

必须重构成可计算、可验证、可追踪和可动态调整的计划。

---

# 2. 重构原则

整套系统按照下面六条原则重构。

## 原则一：主 Agent 管目标，子 Agent 管单域执行

```text
Main Agent：
What should be done?

Sub Agent：
How should this task be completed?
```

主 Agent 不决定具体调用 Milvus 还是 Fetch。

子 Agent 不修改全局目标和任务优先级。

---

## 原则二：Agent、Skill、Tool 严格分层

```text
Agent
= 围绕目标自主决策

Skill
= 告诉 Agent 这类任务应该怎么做

Tool / MCP
= 真正执行外部动作
```

---

## 原则三：Reflection 和 Evaluation 不是同一个东西

这是后续面试非常重要的一点。

### Reflection

属于 Agent 执行过程内部：

```text
我刚才完成得好吗？
有没有明显遗漏？
是否需要补一次检索？
```

特点：

- LLM 驱动；
- 用于局部自我修正；
- 发生在任务完成之前；
- 不作为最终客观评测标准。

### Validation

属于运行时硬性检查：

```text
是否真的返回岗位 ID？
是否包含必须证据？
是否调用了禁止工具？
报告 artifact 是否存在？
数据时间是否自洽？
```

特点：

- 尽量确定性；
- 可以阻断 completed；
- 直接服务任务状态机。

### Evaluation

属于系统质量评估：

```text
这次 Agent 整体表现怎么样？
与金标 Case 相比是否正确？
不同版本相比是否退化？
```

特点：

- 在线 / 离线；
- 基于 trace、state 和 observation；
- 主要用于回归、分析、统计；
- 默认不应让每次请求都增加大量 Judge 成本。

---

## 原则四：所有重要结论都必须能回到 Evidence

最终报告中的事实不能只是：

```text
模型认为这个岗位竞争较小
```

而应该有：

```text
Claim
↓
Evidence IDs
↓
Source
↓
Retrieved Time
↓
Confidence
```

---

## 原则五：最终 Artifact 必须有 Schema

报告和复习计划不能直接：

```text
LLM → Markdown
```

而应该：

```text
Structured Domain State
       ↓
Artifact Composer
       ↓
JSON Schema
       ↓
Artifact Validator
       ↓
Renderer
       ↓
Markdown / UI
```

---

## 原则六：Trace 是基础设施，但不能污染用户报告

```text
User Report
Evaluation
Trace / Evidence
```

应该是三个不同层级。

用户可以看证据和轨迹，但最终正文不能直接塞内部 tool trace。

---

# 3. 推荐总体架构：方案 B 升级版

当前仍然推荐方案 B，而不是立即切方案 C。

```text
                           User Request
                                │
                                ↓
                      ┌───────────────────┐
                      │     Main Agent    │
                      │ Plan-and-Execute  │
                      └─────────┬─────────┘
                                │
                         TodoWrite / DAG
                         Task Contracts
                                │
                ┌───────────────┼───────────────┐
                ↓               ↓               ↓
       ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
       │ PositionAgent  │ │ EvidenceAgent  │ │ AnalysisAgent  │
       │ ReAct          │ │ ReAct          │ │ ReAct/Reason   │
       │ + Reflection   │ │ + Reflection   │ │ + Reflection   │
       └───────┬────────┘ └───────┬────────┘ └───────┬────────┘
               │                  │                  │
               ↓                  ↓                  ↓
           Tool Gateway      Tool Gateway        Calculator /
               │                  │             Evidence Store
               │           Milvus / Search
          PostgreSQL       Fetch / Playwright
               │                  │
               └──────────────────┼──────────────────┘
                                  ↓
                        Structured AgentResult
                                  ↓
                         Runtime Validation Gate
                         ┌────────┼────────┐
                         ↓        ↓        ↓
                      PASS     PARTIAL    FAIL
                         │        │        │
                         ↓        ↓        ↓
                  Update Todo   Replan   Retry/Error
                         │
                         ↓
                       Main Agent
                         │
                 All objectives done?
                         │
                         ↓
                 ┌───────────────────┐
                 │ Artifact Composer │
                 │ Report / StudyPlan│
                 └─────────┬─────────┘
                           ↓
                  Artifact Validation
                           ↓
                       Final Output
                           │
                           ↓
                  Observation Adapter
                           ↓
                ┌──────────────────────┐
                │ Existing Eval Layer  │
                │ Online + Offline Eval│
                └──────────────────────┘
```

---

# 4. 主 Agent：Plan-and-Execute

主 Agent 只保留六类职责：

```text
1. Understand
2. Plan
3. Route
4. Monitor
5. Replan
6. Synthesize
```

## 4.1 主 Agent 不规划工具调用

不要生成：

```text
Todo 1：调用 PostgreSQL
Todo 2：调用 Milvus
Todo 3：调用 SearXNG
Todo 4：调用 Fetch
```

应该生成：

```text
Todo 1：筛选满足用户硬性条件的候选岗位
Todo 2：核验候选岗位涉及的专业和学历政策
Todo 3：为重点岗位补充历史进面分数和竞争信息
Todo 4：综合证据完成岗位匹配与风险分析
Todo 5：生成最终决策报告
Todo 6：根据考试周期和用户基础生成复习计划
```

---

# 5. TodoWrite 升级为 Task Contract

建议 Todo Schema：

```json
{
  "id": "todo_03",
  "objective": "补充重点岗位的历史进面分数和竞争信息",
  "agent_type": "evidence",
  "dependencies": ["todo_01"],
  "required_inputs": [
    "candidate_positions"
  ],
  "required_evidence": [
    "historical_interview_score"
  ],
  "completion_criteria": [
    "至少返回一个可核验来源",
    "明确数据年份",
    "明确对应岗位代码或部门",
    "无法获得官方数据时必须标记不确定性"
  ],
  "priority": "high",
  "status": "pending"
}
```

Task Contract 是整个系统连接：

```text
Planner
SubAgent
Reflection
Validation
Evaluation
```

的核心协议。

---

# 6. 固定三个核心子 Agent

## 6.1 PositionAgent

职责：

> 只负责结构化岗位数据筛选、查询、统计和整理。

Allowed Tools：

```text
postgres_search_positions
postgres_get_position
postgres_statistics
```

禁止：

```text
联网
政策解释
竞争数据搜索
报告生成
```

---

## 6.2 EvidenceResearchAgent

职责：

> 根据一个明确的信息需求搜集、验证和整理 Evidence。

合并原本可能存在的：

```text
政策检索 Agent
网页核验 Agent
进面分数 Agent
报录比 Agent
政策回答 Agent 中的检索部分
```

### 推荐工具层次

```text
policy_search
    ↓
Milvus

web_search
    ↓
SearXNG

web_fetch
    ↓
Fetch MCP

web_browser
    ↓
Playwright MCP
```

运行顺序不是写死，但 Skill 中应规定优先级：

```text
Local Knowledge
    ↓ 不足
Search
    ↓
Fetch
    ↓ 不足 / 动态页面
Browser
```

---

## 6.3 AnalysisAgent

职责：

```text
资格匹配
风险识别
竞争分析
岗位排序
证据冲突分析
```

默认不提供 Browser。

发现证据不足时返回：

```json
{
  "status": "need_evidence",
  "missing_information": [
    {
      "type": "interview_score",
      "position_id": "xxx"
    }
  ]
}
```

由 Main Agent 生成新的 Evidence Todo。

---

# 7. Report 和 StudyPlan 改成 Skill + Artifact Composer，而不是 Agent

建议减少：

```text
ReportGeneratorAgent
StudyPlanAgent
```

的自主决策职责。

如果它们当前只是：

```text
已有数据
→ Prompt
→ 格式化输出
```

更适合：

```text
report_generation Skill
study_plan_generation Skill
+
Artifact Composer
```

它们不需要自由调用一大堆工具。

如果数据不够：

> 不允许 Artifact Composer 自己偷偷查数据。

必须把 missing requirement 返回 Main Agent，由 Planner 创建新的 Todo。

这样保证数据链路可评测。

---

# 8. 子 Agent 内部统一为 ReAct + Reflection

经典结构：

```text
Task Contract
     ↓
Reason
     ↓
Action
     ↓
Observation
     ↓
Reason
     ↓
...
     ↓
Candidate Result
     ↓
Reflection
     ↓
需要修复？
  ├─ Yes → Repair Instruction → ReAct
  └─ No  → Validation Gate
```

---

# 9. Reflection 的正确定位

Reflection 不应该在每一步工具调用后执行。

建议只在：

```text
准备 Finish
```

时触发。

最大：

```text
MAX_REFLECTION_ROUNDS = 1~2
```

## Evidence Agent Reflection

检查：

```text
是否回答任务目标
来源是否可靠
年份是否正确
岗位代码是否一致
多个来源是否冲突
是否存在只引用第三方但声称为官方的情况
```

## Position Agent Reflection

检查：

```text
用户硬约束是否全部进入查询
是否错误过滤
返回字段是否完整
```

## Analysis Agent Reflection

检查：

```text
判断是否有 Evidence 支持
是否把 Unknown 误判为 No
风险等级是否与证据一致
是否存在无证据排名
```

---

# 10. 新增 Runtime Validation Gate

这是本版本相对上一版最重要的新增模块。

它不是 Agent，也不是 LLM Judge。

它负责：

> **在运行时，用确定性规则检查 Task Contract 是否真的完成。**

---

## 10.1 为什么需要 Validation Gate

当前出现：

```text
compose_snapshot_report
not registered

compose_snapshot_report
blocked by permissions
```

却最后：

```text
status = completed
```

说明现在任务完成判断可能过度依赖：

```text
LLM 不再请求工具
```

但：

```text
LLM Stop
```

只意味着 Loop 停了。

不代表：

```text
业务完成。
```

---

## 10.2 新的任务状态

建议统一：

```text
PENDING
RUNNING
COMPLETED
PARTIAL
NEED_EVIDENCE
BLOCKED
FAILED
```

### COMPLETED

必须：

```text
SubAgentResult.status == success
AND
completion_criteria 全部通过
AND
关键 Tool 没有未恢复错误
```

### PARTIAL

例如：

```text
找到岗位和政策
但缺少进面分数
```

### BLOCKED

例如：

```text
关键 Tool 被权限拒绝
```

### FAILED

例如：

```text
工具连续失败
或达到最大 ReAct Step
```

---

# 11. Validation Gate 应验证什么

## 11.1 通用验证

```text
required fields 是否存在
status 是否与 trace 一致
required evidence 是否存在
forbidden tool 是否使用
关键 tool error 是否恢复
task completion criteria 是否满足
```

---

## 11.2 Report Artifact 验证

报告只有满足：

```text
report_artifact != null
schema_valid = true
critical_sections_complete = true
```

才能标记报告生成完成。

如果：

```text
compose_snapshot_report 没注册
```

应该：

```text
BLOCKED / FAILED
```

绝不能 completed。

---

## 11.3 StudyPlan Artifact 验证

至少检查：

```text
总周数一致
阶段周数加和 = 总周数
阶段学习时间可计算
科目时间加和 = 总可用时间
每日学习时长不超过用户可用时间
所有周都有明确目标
所有核心模块至少被覆盖
模考 / 复盘有实际安排
```

---

# 12. 保留并强化当前已有评测体系

当前 GwyPilot 已经实现了：

```text
backend/app/gwy/evals/
```

核心对象：

```text
EvalCase
ExpectedOutcome
AgentObservation
ScoreBundle
CaseResult
EvalConfig
```

这一层是本次重构的重点保留对象，而不是重新设计一套。

---

# 13. 当前评测能力应该继续保留

## 13.1 task_success

继续判断：

```text
任务是否达到 expected final status
是否需要报告
是否需要澄清
是否完成推送
是否发生 error
```

重构后建议直接消费 Validation Gate 的状态。

也就是说：

```text
Agent 自称 success
```

不再直接决定 `task_success`。

而是：

```text
validated_status
```

作为核心输入。

---

## 13.2 tool_call scorer

当前已经支持：

```text
required_tool_recall
tool_precision
tool_f1
forbidden_tool_violation_rate
argument_accuracy
```

这与新架构天然适配。

尤其固定三个 Agent 后，可以增加：

```text
Agent Role Tool Compliance
```

例如：

```text
PositionAgent 调用 web_browser
= role violation

AnalysisAgent 直接查 PostgreSQL
= role violation
```

这比单纯看 forbidden tools 更能验证：

> Agent 是否遵守自己的职责边界。

---

## 13.3 job_constraint scorer

继续保留：

```text
constraint_violation_rate
job_precision
job_recall
job_f1
```

这是岗位筛选最重要的确定性指标。

对公务员岗位场景：

> **硬性约束违反率应该是比“回答写得好不好”更高优先级的指标。**

例如：

```text
用户要求硕士
却推荐本科岗位

用户非党员
却推荐仅限党员岗位
```

这种问题应该直接视为 critical failure。

---

# 14. RAG / Evidence Eval

目前已有：

```text
recall_at_k
citation_support_rate
answer_point_coverage
```

很好，不建议换掉。

新架构中建议进一步补：

```text
source_authority_score
evidence_freshness
evidence_conflict_rate
claim_groundedness
```

注意：

> 这是新增建议，不是当前已经实现的 scorer。

---

## 14.1 Evidence Source Quality

网页数据应该分级：

```text
A
官方国家 / 省级公务员网站
招录机关官网
官方 PDF

B
政府媒体 / 官方公众号

C
大型考试平台

D
论坛 / 博客 / 用户分享
```

可以把：

```text
source_level
```

直接写进 Evidence。

---

# 15. Memory Eval

当前已经有：

```text
memory_field_accuracy
memory_update_accuracy
leakage_count
stale_field_usage_count
```

与现有：

```text
Short-term Context Compact
+
Redis Long-term Memory
+
Side Query
```

保持一致。

建议重构后另外关注：

```text
是否把一次性事实错误写成长时记忆
是否错误覆盖用户长期偏好
是否在无关任务召回旧记忆
```

---

# 16. Efficiency Eval

当前已有：

```text
tool_call_count
agent_steps
latency_ms
input_tokens
output_tokens
estimated_cost
```

重构后非常有意义。

因为要验证：

> 子 Agent 从很多小 Agent 收敛为三个大角色之后，是否真的减少了调用和上下文开销。

建议对比重构前后：

```text
平均 Agent Steps
平均 Tool Calls
平均 LLM Calls
平均 Latency
Token
Success Rate
```

不能只证明“架构更漂亮”，而要证明：

> **效果不降，成本更低，失败更可解释。**

---

# 17. Agent 执行是否正确：推荐四层评测

这是面试时最重要的回答框架。

不要只说：

```text
看最终回答。
```

应该拆成：

```text
Layer 1：Task / Business Correctness
Layer 2：Trajectory / Tool Correctness
Layer 3：Evidence / Groundedness
Layer 4：Final Answer Quality
+
Engineering Efficiency
```

---

## Layer 1：任务结果是否正确

例如岗位筛选：

```text
有没有推荐禁报岗位
岗位 precision / recall
硬约束 violation
是否完成用户真正目标
```

对应当前：

```text
task_success
job_constraint
```

---

## Layer 2：Agent 执行轨迹是否正确

例如：

```text
本来应该查 PostgreSQL，是否真的查了
是否错误调用浏览器
是否反复调用同一工具
工具参数是否正确
是否触发 forbidden tool
```

对应：

```text
tool_call
trace
```

---

## Layer 3：回答是否有事实依据

例如：

```text
进面分数来自哪里
政策引用是否支持结论
召回内容是否命中 gold
回答关键点是否被证据覆盖
```

对应：

```text
rag scorer
citations
evidence
```

---

## Layer 4：最终回答质量

当前确定性指标可以判断：

```text
是否完整
是否覆盖关键点
是否包含必须字段
```

但：

```text
是否清晰
是否真的有决策价值
是否风险解释合理
是否结构易读
```

这类更主观的问题，建议增加：

> **可选 LLM Judge**

而不是把 LLM Judge 作为唯一指标。

---

# 18. LLM Judge 的推荐定位

当前系统以确定性 scorer 为主是正确的。

未来可以增加：

```text
answer_quality_judge
```

但仅评：

```text
Correctness
Completeness
Groundedness
Usefulness
Clarity
```

每项：

```text
1~5
```

并要求返回：

```json
{
  "correctness": 4,
  "completeness": 5,
  "groundedness": 5,
  "usefulness": 4,
  "clarity": 4,
  "reason": "...",
  "critical_issue": null
}
```

### 不建议

```text
一个 LLM Judge 总分
=
系统最终质量
```

因为 Judge 本身：

- 有随机性；
- 有模型偏好；
- 不适合判断 SQL 硬约束；
- 不适合精确验证岗位 ID；
- 不适合验证工具参数。

因此：

```text
Deterministic Scorer = Base Line
LLM Judge = Subjective Supplement
```

---

# 19. 在线 Eval 和离线 Eval 的职责区分

当前已有两套模式是正确的。

## 在线评测

用途：

```text
真实运行持续观察
问题 Case 发现
Trace 采样
版本趋势
```

不要求每次都做昂贵 Judge。

适合：

```text
记录 Tool / Trace
关键确定性指标
抽样 Judge
```

---

## 离线数据集评测

用途：

```text
版本上线前 Regression
Prompt 改动验证
模型切换
Tool 改动
Agent 架构重构对比
```

这次 Agent Loop 重构必须建立：

```text
Before / After Benchmark
```

---

# 20. 建议增加的离线数据集

当前 dev / holdout 可以继续用。

建议把数据集按能力拆开。

```text
datasets/
├── planner/
├── position_filter/
├── policy_rag/
├── evidence_web/
├── analysis/
├── memory/
├── long_task/
├── report/
└── study_plan/
```

---

# 21. Planner Eval

新的 Main Agent 使用 Plan-and-Execute 后，需要单独评 Planner。

建议指标：

```text
plan_goal_coverage
todo_redundancy_rate
dependency_accuracy
agent_route_accuracy
invalid_todo_rate
replan_success_rate
```

### 例子

用户：

```text
帮我筛岗位、查进面分数并给学习计划
```

正确 Plan 至少应该覆盖：

```text
岗位筛选
证据补充
风险分析
复习规划
```

如果漏掉：

```text
复习规划
```

就是 plan_goal_coverage 不完整。

---

# 22. SubAgent Eval

三个 Agent 分开评。

## PositionAgent

```text
constraint_violation_rate
job_precision
job_recall
sql_filter_correctness
role_tool_violation
```

---

## EvidenceResearchAgent

```text
rag_recall_at_k
citation_support
official_source_rate
evidence_freshness
conflict_detection_rate
web_search_success_rate
role_tool_violation
```

---

## AnalysisAgent

```text
unsupported_claim_rate
risk_coverage
qualification_accuracy
ranking_consistency
missing_evidence_detection_rate
```

---

# 23. Reflection Eval

Reflection 也应该评，不是“加了 Reflection 就一定更好”。

建议：

```text
reflection_trigger_count
reflection_repair_success_rate
false_repair_rate
average_reflection_rounds
```

例如：

```text
第一版结果错误
→ Reflection 发现问题
→ 第二版修正
```

这是：

```text
repair success
```

如果：

```text
第一版已经正确
→ Reflection 强行修改成错误
```

就是：

```text
false repair
```

---

# 24. Trace 完整性继续作为关键工程指标

当前已有：

```text
trace_complete
```

应该继续保留。

并建议加入：

```text
TaskCreated
TaskStarted
AgentRouted
ToolUse
ToolResult
Reflection
Validation
TaskCompleted
ArtifactCreated
ArtifactValidated
Stop
```

这样以后可以完整回答：

> **为什么这个 Agent 最后得到这个结果？**

---

# 25. 统一 Observation Adapter

现有：

```text
backend/app/gwy/evals/adapters/agent_adapter.py
```

继续保留。

新架构只需要保证所有结果都能标准化为：

```text
AgentObservation
```

建议新增：

```text
plan
todos
agent_routes
validation_results
reflection_results
artifact_metadata
evidence_quality
```

这样 Eval Layer 不依赖某个 Agent 私有结构。

---

# 26. Final Report 必须彻底重构

当前的“报告正文 + 工具 Chip + Trace”不能作为最终产品。

建议把页面拆成：

```text
Tab 1：分析报告
Tab 2：证据与来源
Tab 3：执行轨迹
Tab 4：评测结果（开发 / 管理模式）
```

普通用户默认只看：

```text
分析报告
```

---

# 27. Job Analysis Report 应该长什么样

## 第一部分：决策摘要

不是重复 Query。

而应该直接告诉用户：

```text
共筛选 42 个原始岗位
硬约束过滤后剩余 11 个
进一步政策核验后 8 个可报
其中：
高推荐 3 个
中推荐 3 个
谨慎报考 2 个
```

并说明主要原因：

```text
专业匹配度
学历匹配
地区偏好
历史竞争
限制条件
```

---

# 28. 推荐岗位应该是决策卡，而不是一段文字

例如：

```text
# Top 1 成都某税务局 一级行政执法员

推荐等级：A
匹配度：92%
报考资格：满足
竞争风险：中等
证据置信度：高

为什么推荐：
- 专业完全匹配
- 硕士学历满足
- 无政治面貌限制
- 招录 3 人，相比同地区同类岗位更友好

风险：
- 近两年最低进面分数分别为 xxx / xxx
- 报录比较高
- 应届身份要求需确认

关键证据：
[政策 1]
[官方公告 2]
[2025 面试名单 3]
```

---

# 29. 报告推荐结构

```text
1. Executive Summary
2. 用户画像与筛选条件
3. 筛选过程摘要
4. Top N 岗位推荐
5. 岗位逐项风险分析
6. 政策核验结果
7. 竞争信息
8. 不确定项 / 缺失证据
9. 报考策略建议
10. 下一步行动清单
11. Evidence Sources
12. 数据时间与免责声明
```

---

# 30. Report Artifact Schema

不要直接存 Markdown。

先生成：

```json
{
  "report_id": "...",
  "generated_at": "...",
  "profile_snapshot": {},
  "screening_summary": {
    "raw_count": 42,
    "eligible_count": 8
  },
  "ranked_positions": [
    {
      "position_id": "...",
      "rank": 1,
      "recommendation_level": "A",
      "match_score": 0.92,
      "qualification_status": "eligible",
      "competition_risk": "medium",
      "evidence_confidence": "high",
      "reasons": [],
      "risks": [],
      "evidence_ids": []
    }
  ],
  "uncertainties": [],
  "action_items": [],
  "evidence_index": []
}
```

然后：

```text
Schema
→ Markdown Renderer
→ UI Renderer
```

这样才能：

- 验证；
- 前端稳定展示；
- 做 report eval；
- 后续导出 PDF。

---

# 31. Report Validation

建议确定性检查：

```text
ranked_positions 非空
每个岗位都有 position_id
推荐岗位不得出现 hard constraint violation
重要事实都有 evidence_id
不存在 citation 指向不存在 Evidence
不确定数据必须标记 uncertainty
generated_at 必须存在
```

如果没通过：

```text
report_status = invalid
```

不能把整个任务设为 completed。

---

# 32. Report Eval

建议新增：

```text
report_schema_valid
report_section_coverage
unsupported_claim_rate
evidence_coverage
recommendation_constraint_violation
actionability_score
```

其中前五项尽量确定性。

`actionability_score` 可以使用可选 LLM Judge。

---

# 33. 复习规划应该从“静态时间表”升级成 Planning Artifact

复习规划不能只根据：

```text
16 周
8 小时/天
50% 行测
50% 申论
```

直接生成。

至少需要输入：

```text
exam_date
current_date
study_days_per_week
available_hours_by_day
baseline_scores
weak_modules
target_score
exam_type
completed_modules
mock_history
```

---

# 34. 总学习时间必须由阶段计划反推，而不是顶部写死

例如：

```text
基础期：5周 × 7天 × 4h = 140h
强化期：5周 × 7天 × 6h = 210h
冲刺期：6周 × 7天 × 8h = 336h

Total = 686h
```

那么顶部应该显示：

```text
总计划时长：686 小时
阶段最高强度：8 小时/天
平均计划强度：6.1 小时/天
```

而不是：

```text
每日学习时长：8 小时
```

除非真的每一天都 8 小时。

---

# 35. 更推荐引入 study_days_per_week

现实情况下可以：

```text
6 天学习 + 1 天复盘 / 休息
```

那么：

```text
基础期：
5 × 6 × 4 = 120h

强化期：
5 × 6 × 6 = 180h

冲刺期：
6 × 6 × 8 = 288h

Total = 588h
```

再根据实际基础分配：

```text
行测 58%
申论 42%
```

而不是永远：

```text
50 / 50
```

---

# 36. 学科时间分配应该可解释

例如：

```text
行测当前：61
目标：75
差距：14

申论当前：67
目标：72
差距：5
```

则系统可以给出：

```text
行测 60%
申论 40%
```

理由：

```text
行测提升空间更大
且部分模块可通过专项训练快速提分
```

---

# 37. 复习计划必须有三个层级

## Level 1：阶段

```text
基础期
强化期
冲刺期
```

---

## Level 2：周计划

例如：

```text
Week 3

行测：
- 数量关系：工程问题
- 判断推理：图形推理

申论：
- 归纳概括
- 2 套材料训练

目标：
- 图推正确率 ≥ 75%
- 归纳概括评分 ≥ 70%
```

---

## Level 3：每日任务

例如：

```text
09:00-10:30
图形推理 30 题

10:40-11:20
错题复盘

14:00-16:00
申论归纳概括 2 题

19:00-20:00
当日错题二刷
```

---

# 38. 每一周必须有可验收 Output

不能只是：

```text
“系统梳理知识点”
```

而应该：

```text
完成：
300 道判断推理题
2 次专项限时
1 次错题重做
2 篇申论小题

验收：
正确率 ≥ 75%
平均用时 ≤ xx
```

这样才可以评测计划有没有执行效果。

---

# 39. Study Plan 必须是动态计划

真正有价值的是：

```text
Generate Plan
    ↓
学习一周
    ↓
Record Performance
    ↓
Mock / Exercise Results
    ↓
Analyze Weakness
    ↓
Replan
```

这与 Agent Harness 本身非常契合。

主 Agent 可以每周生成：

```text
Study Plan Update Todo
```

AnalysisAgent 根据：

```text
最新分数
错题
完成率
剩余时间
```

返回调整建议。

Artifact Composer 再更新计划。

---

# 40. StudyPlan Schema

建议：

```json
{
  "plan_id": "...",
  "exam": "2026 国考",
  "start_date": "...",
  "exam_date": "...",
  "total_weeks": 16,
  "study_days_per_week": 6,
  "total_hours": 588,
  "average_hours_per_study_day": 6.125,
  "baseline": {
    "xingce": 61,
    "shenlun": 67
  },
  "target": {
    "xingce": 75,
    "shenlun": 72
  },
  "subject_allocation": {
    "xingce": 0.60,
    "shenlun": 0.40
  },
  "phases": [],
  "weeks": [],
  "review_rules": {
    "weekly_replan": true,
    "mock_interval_weeks": 2
  }
}
```

---

# 41. StudyPlan Validation

至少检查：

```text
phases.weeks sum == total_weeks

phase total hours
==
weekly total hours sum

subject hours sum
==
total_hours

daily hours
<=
user availability

所有 week
都有 measurable output

冲刺阶段
必须包含 full mock

所有主要科目
都有覆盖
```

---

# 42. StudyPlan Eval

新增：

```text
time_consistency
module_coverage
weakness_alignment
target_alignment
weekly_output_coverage
mock_test_coverage
feasibility
```

### time_consistency

完全可以确定性评分。

### feasibility

部分规则 + 可选 LLM Judge。

例如：

```text
用户每天最多 4h
计划安排 8h
```

直接失败，不需要 Judge。

---

# 43. 报告、复习计划和 Eval 之间形成闭环

最终：

```text
Domain State
   ↓
Report Artifact
   ↓
Report Validator
   ↓
Report Eval

Domain State
   ↓
StudyPlan Artifact
   ↓
StudyPlan Validator
   ↓
StudyPlan Eval
```

而不是：

```text
LLM 生成一段文本
→ completed
```

---

# 44. 前端页面建议重新划分

## 报告页面

```text
[岗位分析报告]

Overview
Top Recommendations
Risk Matrix
Policy Verification
Competition Evidence
Action Items
```

独立：

```text
[Evidence]
[Agent Trace]
[Evaluation]
```

---

## 复习计划页面

顶部不要再放互相矛盾的数字。

建议：

```text
考试：2026 国考
剩余：16 周
总计划时长：588h
学习日：6天/周
平均：6.1h/学习日
当前阶段：基础期
下次模考：xx
```

主体：

```text
阶段路线
↓
本周重点
↓
本周具体计划
↓
今日任务
↓
当前完成率
↓
薄弱项变化
↓
下周调整建议
```

---

# 45. Eval 前端继续保留 Run / Case / Trace / Score 分层

现有评测前端已经可以：

```text
Dataset
Run
Case
Observation
Trace
Scores
Failure Reasons
```

这是正确的。

重构后建议增加：

```text
Plan
Task Contracts
Agent Route
Reflection
Validation Result
Artifacts
```

这样一次 Case 可以完整回答：

```text
Planner 为什么这么拆？
派给了哪个 Agent？
Agent 调了什么 Tool？
拿到了什么 Evidence？
Reflection 改了什么？
Validation 为什么判成功？
最后 Report 怎么来的？
哪些 scorer 通过 / 失败？
```

---

# 46. 推荐新增 Failure Taxonomy

评测不能只有：

```text
failed
```

应该分类：

```text
PLAN_ERROR
ROUTING_ERROR
TOOL_ERROR
PERMISSION_BLOCKED
RETRIEVAL_MISS
EVIDENCE_CONFLICT
HALLUCINATION
CONSTRAINT_VIOLATION
REFLECTION_FAILURE
VALIDATION_FAILURE
ARTIFACT_INVALID
MEMORY_ERROR
TIMEOUT
```

这对面试和工程分析都很有价值。

---

# 47. 一次完整任务的新执行链路

用户：

```text
帮我筛选成都适合我的国考岗位，
重点比较竞争情况，
再给我后续复习计划。
```

---

## 47.1 Main Agent Planning

生成：

```text
Todo 1：筛选满足硬约束的成都岗位
→ PositionAgent

Todo 2：核验候选岗位专业和报考政策
→ EvidenceAgent

Todo 3：补充重点岗位进面分数 / 竞争证据
→ EvidenceAgent

Todo 4：岗位匹配、风险和推荐排序
→ AnalysisAgent

Todo 5：生成 Job Analysis Report Artifact

Todo 6：根据目标岗位和当前基础生成 StudyPlan Artifact
```

---

## 47.2 PositionAgent

```text
Reason
↓
PostgreSQL
↓
Observation
↓
补充字段查询
↓
Candidate Result
↓
Reflection
↓
Validation
```

输出：

```text
8 个 eligible positions
```

---

## 47.3 EvidenceAgent

先：

```text
Milvus
```

发现进面分数缺失：

```text
SearXNG
↓
Fetch
↓
必要时 Playwright
```

形成：

```text
Evidence Store
```

---

## 47.4 AnalysisAgent

基于：

```text
Positions
Policy Evidence
Competition Evidence
User Profile
```

生成：

```text
Ranked Position Analysis
```

如证据不足：

```text
NEED_EVIDENCE
```

Main Agent 动态 Replan。

---

## 47.5 Report Artifact

只消费：

```text
Validated Domain State
```

生成：

```text
Structured Report JSON
```

通过：

```text
Report Validator
```

以后：

```text
render UI / Markdown
```

---

## 47.6 Study Plan Artifact

消费：

```text
Exam Date
Target Positions
Required Subjects
Baseline
Available Hours
Weakness
```

生成：

```text
Structured StudyPlan
```

再经过：

```text
Time Consistency Validator
Coverage Validator
Feasibility Validator
```

---

## 47.7 Online Eval

最后：

```text
AgentObservation Adapter
↓
record_online_evaluation()
```

记录：

```text
task_success
tool_call
job_constraint
rag
memory
efficiency
```

并追加新指标：

```text
planner
validation
report
study_plan
```

---

# 48. 推荐重构目录

```text
backend/app/gwy/

agent_runtime/
├── loop.py                  # 保留现有通用 Loop
├── planner.py
├── scheduler.py
├── task_contract.py
├── validation.py
└── result.py

agents/
├── base_react_agent.py
├── position_agent.py
├── evidence_agent.py
└── analysis_agent.py

reflection/
├── reflector.py
└── criteria.py

skills/
├── position_screening/
├── policy_verification/
├── web_research/
├── risk_analysis/
├── report_generation/
└── study_plan_generation/

tools/
├── postgres/
├── milvus/
├── searxng/
└── mcp/
    ├── fetch/
    └── playwright/

evidence/
├── schemas.py
└── store.py

artifacts/
├── report/
│   ├── schema.py
│   ├── composer.py
│   ├── validator.py
│   └── renderer.py
└── study_plan/
    ├── schema.py
    ├── composer.py
    ├── validator.py
    └── renderer.py

evals/
├── schemas.py               # 保留
├── run_eval.py              # 保留
├── service.py               # 保留
├── adapters/
│   └── agent_adapter.py     # 扩展
└── scorers/
    ├── task_success.py
    ├── tool_call.py
    ├── job_constraint.py
    ├── rag.py
    ├── memory.py
    ├── efficiency.py
    ├── planner.py           # 新增建议
    ├── validation.py        # 新增建议
    ├── report.py            # 新增建议
    └── study_plan.py        # 新增建议
```

---

# 49. 分阶段改造顺序

不要一次性全部重写。

## Phase 0：先修完成状态问题

第一优先级：

```text
Tool 未注册
权限阻断
Artifact 为空
```

不能再返回：

```text
completed
```

实现：

```text
Runtime Validation Gate
```

---

## Phase 1：固定 Agent Registry

收敛为：

```text
PositionAgent
EvidenceAgent
AnalysisAgent
```

---

## Phase 2：Todo → Task Contract

加入：

```text
agent_type
dependencies
required_inputs
required_evidence
completion_criteria
```

---

## Phase 3：SubAgent → ReAct + Reflection

去掉子 Agent 内部不必要的固定 Workflow。

---

## Phase 4：统一 AgentResult + Evidence

所有子 Agent 输出统一协议。

---

## Phase 5：重做 Report Artifact

先 Schema，再 Renderer。

不要先调 Prompt。

---

## Phase 6：重做 StudyPlan Artifact

先修：

```text
时间数学一致性
```

再做：

```text
个性化
动态调整
```

---

## Phase 7：扩展现有 Eval

不重写 Eval。

增加：

```text
Planner Scorer
Role / Routing
Validation
Report
StudyPlan
```

---

## Phase 8：Before / After Regression

使用：

```text
dev
holdout
```

比较：

```text
旧 Agent Loop
vs
新 Agent Loop
```

最终必须拿到量化结果。

---

# 50. 建议版本对比指标

例如：

| Metric | Old | New |
| --- | ---: | ---: |
| End-to-End Success | | |
| Job Constraint Violation | | |
| RAG Recall@K | | |
| Citation Support | | |
| Required Tool Recall | | |
| Forbidden Tool Violation | | |
| Avg Agent Steps | | |
| Avg Tool Calls | | |
| Latency P50 | | |
| Latency P95 | | |
| Input Tokens | | |
| Output Tokens | | |
| Reflection Repair Rate | | |
| Artifact Validation Pass | | |
| StudyPlan Time Consistency | | |

这样整个重构最后可以形成非常有说服力的项目结果：

> 重构前后不仅架构更清晰，而且能够通过离线数据集和在线 trace 量化验证任务成功率、工具调用正确性、RAG 证据质量、岗位硬约束、报告完整度和复习计划可执行性。

---

# 51. 方案 B 与方案 C 最终取舍

## 方案 B：当前推荐

```text
Main Agent
= Plan-and-Execute

SubAgent
= ReAct + Reflection

Runtime
= Validation Gate

Eval
= Existing Trace-based Eval Layer

Final Output
= Structured Artifacts
```

优点：

- 对现有代码改动相对可控；
- 能复用当前 AgentRuntime；
- 能复用 Tool、Permission、Recovery；
- 能复用现有 Eval；
- 能立刻解决 Agent 过多和职责混乱；
- 适合当前项目阶段。

---

## 方案 C：后续演进

```text
Planner
↓
Executor
↓
Verifier
↓
Reporter
```

它适合未来：

```text
评测数据充分
流程稳定
模块边界稳定
希望做强审计 / 企业级部署
```

但当前直接切 C 会：

- 引入更多组件；
- 增加 LLM 调用；
- 改动较大；
- 与当前已有 Runtime 重叠。

所以现在没有必要。

---

# 52. 面试时如何回答“怎么判断 Agent 执行是否正确？”

推荐回答：

> 我不会只看 Agent 最后的自然语言回答，而是分四层评测。第一层看任务结果，比如岗位推荐有没有违反学历、专业、政治面貌等硬约束；第二层看执行轨迹，通过 trace 检查 Agent 有没有调用正确工具、参数是否正确、是否出现禁止工具或重复调用；第三层看证据质量，比如 RAG Recall@K、引用支持率以及答案关键点覆盖率，保证结论可以被实际证据支撑；第四层再看最终回答的完整性、可读性和决策价值。前三层尽量使用确定性 scorer，主观质量再用可选的 LLM Judge 补充。同时我会用离线金标数据集做版本回归，线上则持续记录 trace、耗时、token 和失败原因，这样可以判断一个 Agent 不只是“回答看起来对”，而是真正从执行过程到结果都有可验证性。

如果面试官继续问：

> Reflection 不就是评测吗？

可以回答：

> 不是。Reflection 是 Agent 在执行过程中的自我纠错机制，它仍然依赖模型自身判断；真正的 Evaluation 应该站在 Agent 外部，通过金标、业务规则、工具轨迹和证据进行验证。我的系统里 Reflection 用来提高单次任务成功率，而 Eval 用来判断整个系统是否真的变好了。

---

# 53. 这次重构之后项目最值得写进简历的描述

可以升级为：

> 基于 Agent Runtime 重构分层 Agent Harness，主 Agent 采用 Plan-and-Execute 进行复杂任务拆解、动态调度与 Replan，固定领域子 Agent 基于 ReAct 实现 PostgreSQL、Milvus 与 Web 工具的自主选择，并结合 Reflection 与 Completion Criteria 完成局部自校验；设计 Runtime Validation Gate，避免工具失败或权限阻断情况下的伪完成状态。基于可追踪 Trace 构建在线/离线 Agent Eval，覆盖任务成功、工具调用、岗位硬约束、RAG、Memory 与效率指标，并扩展结构化报告和复习计划 Artifact 的一致性与质量评测。

---

# 54. 最终架构一句话总结

```text
Main Agent
负责全局 Plan-and-Execute

Fixed SubAgents
负责单域 ReAct

Reflection
负责 Agent 内部局部纠错

Validation Gate
负责运行时硬性完成判定

Existing Eval Layer
负责系统外部在线 / 离线质量测量

Evidence Store
负责所有事实可追溯

Artifact Composer + Validator
负责生成真正可用的岗位报告和复习规划
```

最终不要再让系统变成：

```text
“模型跑完了”
=
“任务完成了”
```

而应该变成：

```text
Agent 执行
→ 有轨迹
→ 有证据
→ 有反思
→ 有确定性验证
→ 有结构化 Artifact
→ 有在线/离线评测
→ 才能证明任务真正完成且质量可控
```
