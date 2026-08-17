# GwyPilot 项目功能说明（简历素材版）

> 说明：本文基于当前仓库的真实实现与已落地文档整理，尽量用“可直接写进简历”的口径表达，但保留与代码一致的边界，不把规划内容写成既成事实。

## 1. 项目定位

GwyPilot 是一个面向公务员考试场景的智能辅助系统，核心目标是把“岗位检索、政策问答、资格核验、风险判断、复习计划生成、报告输出”串成一条可追踪、可回放、可评测的 Agent 工作流。

项目不是简单的聊天机器人，而是把结构化岗位数据、Milvus 知识检索、网页证据核验、只读数据库查询、任务规划、工具调用、trace 记录和评测体系整合成一套 Agent Runtime。

## 2. 核心架构：Agent Runtime 驱动的分层 Agent Harness

当前实现以 `backend/app/gwy/agent_runtime/` 为执行内核，提供统一的 `AgentRuntime`、`ToolRegistry`、`TraceRecorder`、`TaskContract` 和 `ValidationResult`。

从业务表现上看，这套架构接近你关心的经典范式：

- 主 Agent 负责任务拆解、动态调度和必要时的 replan。
- 固定领域子 Agent / 业务工具负责局部任务执行。
- 子 Agent 在具体任务内自主决定下一步调用哪些工具，更接近 ReAct 风格，而不是硬编码固定流程。
- 结果返回后会经过 validation / quality / completion criteria 再判断是否能结束，具备 Reflection 式自校验特征。

换句话说，当前项目不是“单轮问答 + 固定流程”，而是“规划、执行、复核、再调度”的 Agent Loop。

## 3. 主 Agent 如何工作

主流程入口主要集中在：

- `backend/app/gwy/services/autonomous_chat_agent_service.py`
- `backend/app/gwy/services/position_snapshot_runtime_service.py`
- `backend/app/gwy/services/policy_rag_service.py`

主 Agent 的行为可以概括为：

1. 先识别用户意图，判断是政策问答、岗位推荐、快照分析还是通用咨询。
2. 根据任务类型构建上下文，包括用户画像、会话附件、岗位快照、历史 memory、检索条件等。
3. 通过 `todo_tasks` / `todo_write` 形成任务计划，明确子步骤和 evidence 需求。
4. 在 AgentRuntime 中动态决定是否继续检索、是否调用工具、是否需要补证、是否要生成复习计划或最终报告。
5. 将执行过程写入 trace，再把结果汇总成最终回答、报告或分析结果。

这意味着主 Agent 更像“调度器 + 规划器 + 结果整合器”，而不是单一模型 prompt。

## 4. 子 Agent / 领域工具如何工作

项目里已经把多个领域能力拆成了独立模块，比较典型的有：

- `PositionDecisionAgent`
- `RiskReviewAgent`
- `ReportGeneratorAgent`
- `StudyPlanAgent`
- `PolicyEvidenceAgent`
- `WebResearchService`
- `PositionSnapshotRuntimeService`

这些模块的共同特点是：不按死板的固定步骤串行执行，而是围绕输入任务自己决定“缺什么、查什么、用什么工具补齐”。

尤其是岗位分析和政策问答这两类任务，已经具备明显的 ReAct 风格：

- 先观察任务输入和上下文；
- 再选择 PostgreSQL、Milvus、Web 或本地业务逻辑；
- 遇到信息缺口时继续检索或补证；
- 最后基于已获得的证据生成结论。

在岗位推荐、风险复核、报告生成、复习计划生成这些流程里，也都加入了后验检查和质量校验，具备 Reflection / self-check 的味道。

## 5. 任务规划与 completion criteria

项目中不只是“能答”，还强调“答完是否真的完成任务”。

这部分主要体现在：

- `TaskContract`
- `TodoItem`
- `ValidationResult`
- `TraceEvent`
- `search query planner`

运行时会围绕任务目标生成结构化 TODO，子步骤会带上状态、证据需求和依赖关系。最后不是只看模型有没有输出，而是看：

- 任务是否完成；
- 所需证据是否收齐；
- 工具调用是否满足预期；
- 是否还存在缺失项；
- 是否通过 validation gate。

这就是你可以在简历里写成“引入 completion criteria 和 runtime validation gate，避免工具失败或权限阻断导致的伪完成”的原因。

## 6. 上下文管理：短期工作记忆、长期记忆与压缩机制

项目的上下文管理不是简单地把历史消息一直往模型里塞，而是做了分层处理：

- 短期工作记忆：围绕当前会话保存分析进度、任务上下文、最近推荐结果和 compact 摘要。
- 长期记忆：跨会话沉淀用户偏好、岗位选择倾向和历史决策结果。
- 动态补充：当当前问题需要历史背景时，先做按需 side query，再把相关 memory 作为参考信息注入 prompt。
- 上下文压缩：当消息长度过长时，触发 micro compact 或 auto compact，把旧工具结果和过长对话压缩掉，同时保留关键结论和 transcript 引用。
- 附件上下文：在会话中如果用户上传了材料，会先把附件摘要或抽取文本拼进用户 prompt，再交给主 Agent 决策。

对应实现主要分布在：

- `backend/app/gwy/services/agent_memory_service.py`
- `backend/app/gwy/agent_runtime/compact.py`
- `backend/app/gwy/agent_runtime/loop.py`
- `backend/app/gwy/services/autonomous_chat_agent_service.py`

这部分很适合在简历里写成：

> 设计并实现分层上下文管理机制，结合短期工作记忆、长期偏好记忆、按需 side-query 和记忆压缩，支持多轮 Agent 在长上下文任务中保持稳定决策。

## 7. 工具调用体系：统一 MCP Tool 风格

项目把外部能力尽量都收敛成 MCP 风格工具，并通过 `ToolRegistry` 统一注册。

### 6.1 Web MCP

Web 检索与网页证据核验统一走 Web MCP：

- `web_search`
- `web_fetch`
- `browser_retrieve`
- `verify_web_evidence`

适用场景包括：

- 查公告原文；
- 补报录比；
- 补进面分数；
- 查政策解释；
- 网页正文抓取不足时使用浏览器渲染兜底。

### 6.2 DB MCP

只读数据库能力统一走 DB MCP：

- `list_tables`
- `describe_table`
- `sample_rows`
- `query_sql`

它主要服务于结构化岗位表和只读校验，严格限制为只读查询，不允许写入类操作。

### 6.3 Playwright MCP

对动态网页、脚本渲染页面、网页正文抓取不足场景，保留本地兼容 Playwright MCP：

- `read_page`
- 本地启动入口：`python -m app.gwy.mcp_tools.playwright_server`

这让项目在“网页搜索可用，但页面内容必须靠渲染才能拿到”时仍然有可靠兜底。

### 6.4 MCP 调用风格

当前项目已经把 MCP 能力抽象成统一调用链，典型顺序是：

- Web：`web_search -> web_fetch / browser_retrieve -> verify_web_evidence`
- DB：`list_tables -> describe_table / sample_rows -> query_sql`

这比散落的 function call 更适合写成“统一工具层，按能力域分层封装”的简历表述。

## 8. 权限管理：更细的工具级 gate

项目里的权限管理不是简单的“能不能调用”，而是按工具名做了分层控制。

关键实现位于：

- `backend/app/gwy/agent_runtime/permissions.py`

当前逻辑包含：

- deny list：如 `bash`、文件写入、删除记忆等高风险工具直接拒绝；
- ask / review 类工具：按业务规则放行；
- allow list：只读检索、review、todo、memory、MCP 查询等工具允许；
- default deny：未注册工具默认拒绝。

这带来的价值是：

- 防止 Agent 误调用破坏性工具；
- 限制子 Agent 的作用域；
- 让工具调用边界更清晰；
- 避免“看起来完成了，实际上工具没成功”的伪完成状态。

如果你要在简历里写，可以概括成：

> 设计并实现工具级权限 gate，对检索、数据库查询、记忆、报告生成等能力做 allow/deny 控制，降低 Agent 误操作和越权调用风险。

## 9. Trace、hook 和可追踪性

项目非常强调过程可解释，而不是只给最终答案。

trace 相关实现主要包括：

- `TraceRecorder`
- `TraceEvent`
- 各业务服务返回的 `trace` / `retrieval_trace` / `trace_json`
- hook 输出里的子 Agent 启动、结束、工具使用、网页证据步骤等事件

trace 里会尽量记录：

- 原始输入；
- 改写后的查询；
- 调用了哪些工具；
- 工具输入输出；
- 哪一步成功、哪一步失败；
- 哪一步进入了 fallback；
- 哪一步通过了 validation。

这意味着后续排查问题时，不需要只看最终答案，而是可以回放整个决策链路。

## 10. 评测体系：在线 + 离线 + 工程指标

项目已经把评测做成了一套可持续使用的体系，而不是临时脚本。

### 9.1 离线评测

离线评测入口位于 `backend/app/gwy/evals/run_eval.py`，支持对数据集样本进行统一执行和评分。

### 9.2 在线评测

在线评测会把真实运行中的 Agent 输出转成评测记录，便于做回归观察和质量跟踪。

### 9.3 评测关注点

当前评测体系覆盖的维度包括：

- 任务成功率；
- 工具调用是否符合预期；
- 岗位结构化硬约束；
- RAG 召回与引用质量；
- Memory 相关状态；
- Trace 完整性；
- 工程效率指标，如 tool call 次数、耗时、token 等。

这部分很适合写成简历里的“构建了可追踪 trace 驱动的在线/离线 Agent Eval 体系”。

## 11. 你可以直接用于简历的表达

下面这些句子可以直接作为简历素材，按需要再压缩：

- 基于 Agent Runtime 构建分层 Agent Harness，主流程支持任务拆解、动态调度与按需 replan，子任务以 ReAct 风格自主选择 PostgreSQL、Milvus、Web 和 MCP 工具完成局部执行。
- 设计分层上下文管理机制，结合短期工作记忆、长期偏好记忆、按需 side-query 和记忆压缩，在长上下文多轮任务中维持稳定决策与连续性。
- 设计工具级权限 gate，对高风险操作、只读检索、记忆与报告类工具做分层控制，降低 Agent 越权调用与伪完成风险。
- 统一 Web MCP / DB MCP / Playwright MCP 工具层，打通网页搜索、网页正文抓取、动态页面渲染、只读数据库查询等能力，并通过 trace 记录完整调用链路。
- 引入 completion criteria 与 validation 机制，对任务完成度、证据充分性、工具调用结果和报告质量进行后验校验，避免“模型答完但任务未完成”的情况。
- 构建在线/离线 Agent Eval 体系，基于 trace、tool_calls、latency、token、RAG 和 Memory 状态做质量评估与回归分析。
- 针对岗位推荐、政策问答和复习计划生成等场景，建立“检索—验证—复核—输出”的闭环流程，提升结果可解释性和可追踪性。

## 12. 如果你要再压成更像简历的一段话

可以写成：

> 基于 Agent Runtime 重构公务员考试智能辅助系统，主 Agent 负责任务拆解与动态调度，子 Agent 以 ReAct 风格自主调用 PostgreSQL、Milvus、Web 与 MCP 工具完成岗位分析、政策检索和网页证据核验；通过分层上下文管理、工具级权限控制、completion criteria、trace 可追踪机制和在线/离线评测体系，提升了 Agent 的可解释性、稳定性与任务完成率。

如果你愿意，我下一步可以继续帮你把这份文档再压缩成一版“简历项目经历”，控制在 3–5 条、每条一行，直接能贴到简历里。
