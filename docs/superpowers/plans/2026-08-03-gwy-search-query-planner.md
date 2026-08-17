# Gwy 搜索词规划器与统一 Query Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动现有搜索工具、权限控制和运行骨架的前提下，给所有自然语言搜索入口加上一层模型驱动的 Query Planner，让搜索词先被“润色 + 约束 + 展开”，再进入现有的 web / policy 检索链路，并把原始问题、改写后的关键词和实际调用的工具都写进 trace。

**Architecture:** 保留现有 `WebSearchService`、`WebResearchService`、`PolicyRagService`、`PositionAnalysisAgent` 和 `AutonomousChatAgentService` 的职责不变，只在“发起搜索之前”插入一个共享的 `SearchQueryPlannerService`。这个服务复用现有 `ChatService` 走 LLM 改写，输出结构化 `SearchQueryPlan`，包含 `primary_query`、`planned_queries`、`required_source_kinds`、`search_kind` 和 `trace_notes`。如果模型不可用、输出 JSON 不合法，或者上下文太短，就回退到当前的确定性规则，确保不会把搜索链路搞坏。统一入口后，web 检索、政策检索以及岗位分析里的补证搜索都会得到一致的查询表达和更强的 trace 可读性。

**Tech Stack:** FastAPI 后端、现有 `ChatService` / SiliconFlow OpenAI-compatible LLM、Pytest、现有 web / policy / Milvus 检索服务、现有 trace / hook 体系。

## Global Constraints

- 保持 `fastapi/full-stack-fastapi-template` 的原有骨架，不重构运行方式。
- 后端新增代码优先放在 `backend/app/gwy/`。
- 不新增前端页面。
- 不改动现有工具名、权限配置和异常处理边界。
- 现有搜索执行器保持不变：`web_search -> web_fetch -> browser_retrieve` 仍然负责真正拉网页；Planner 只负责改写搜索词，不替代检索。
- 对于模型不可用或输出异常的情况，必须安全回退到当前规则，不能让搜索链路直接失败。
- 所有新的搜索规划 trace 必须可追踪、可回放，明确区分“原始输入 / 模型改写 / 最终调用工具”。

---

### Task 1: 新增共享 Query Planner 的契约、提示词和单元测试

**Files:**
- Create: `backend/app/gwy/services/search_query_planner_service.py`
- Create: `backend/app/gwy/prompts/search_query_planner.py`
- Create: `backend/tests/gwy/test_search_query_planner_service.py`
- Modify: `backend/app/gwy/README.md`（补充 Planner 的入口和字段说明）

**Interfaces:**
- Consumes:
  - `ChatService.chat_completion(...)`
  - 任务上下文中的 `query`、`position`、`search_kind`、`planned_queries`
- Produces:
  - `SearchQueryRequest`
  - `SearchQueryPlan`
  - `SearchQueryPlannerService.plan(...)`

- [ ] **Step 1: 写一个会失败的测试，先把目标行为固定下来**

```python
def test_search_query_planner_expands_competition_query_to_official_candidates() -> None:
    planner = SearchQueryPlannerService(chat_service=FakeChatService(
        response='{"primary_query":"100110001001 2026 报录比 进面分 官方公告","planned_queries":["100110001001 2026 报录比","100110001001 进面分 官方公告","100110001001 site:gov.cn 招录 公告"],"required_source_kinds":["official"],"search_kind":"web","trace_notes":"优先官方来源"}'
    ))

    result = planner.plan(
        SearchQueryRequest(
            query="100110001001 2026报录比 进面人数 进面分",
            search_kind="web",
            position={
                "position_code": "100110001001",
                "department_name": "中央办公厅",
                "job_title": "法务管理岗位一级主任科员及以下",
            },
        )
    )

    assert result.search_kind == "web"
    assert result.required_source_kinds == ["official"]
    assert result.primary_query.startswith("100110001001")
    assert any("官方公告" in item for item in result.planned_queries)
```

```python
def test_search_query_planner_falls_back_when_llm_output_is_invalid() -> None:
    planner = SearchQueryPlannerService(chat_service=FakeChatService(response="not-json"))

    result = planner.plan(
        SearchQueryRequest(
            query="2026 进面分",
            search_kind="web",
            position={"department_name": "某部门", "job_title": "某岗位"},
        )
    )

    assert result.planned_queries
    assert "2026" in result.primary_query
    assert result.trace[-1]["strategy"] == "fallback_rules"
```

- [ ] **Step 2: 运行测试确认当前仓库还没有这个能力**

Run:
`pytest backend/tests/gwy/test_search_query_planner_service.py -q`

Expected: fail with `ModuleNotFoundError` / missing symbol errors。

- [ ] **Step 3: 实现最小可用的 Planner 服务**

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchQueryRequest:
    query: str
    search_kind: str  # "web" | "policy" | "position"
    position: dict[str, Any] | None = None
    planned_queries: list[str] = field(default_factory=list)
    max_queries: int = 5


@dataclass(slots=True)
class SearchQueryPlan:
    original_query: str
    primary_query: str
    planned_queries: list[str]
    required_source_kinds: list[str]
    search_kind: str
    trace: list[dict[str, Any]] = field(default_factory=list)


class SearchQueryPlannerService:
    def __init__(self, *, chat_service: ChatService | None = None) -> None: ...

    def plan(self, request: SearchQueryRequest) -> SearchQueryPlan: ...
```

实现要求：
- 先构造一段稳定的 LLM prompt，明确要求模型返回 JSON。
- 让模型保留岗位编号、年份、岗位名称、官方来源约束、缺口字段。
- 对 `web` 类查询优先生成 `官方公告 / 招考简章 / site:gov.cn / 面试名单 / 进面分` 这类词；对 `policy` 类查询优先保留政策主题词；对 `position` 类查询保留职位名称、地区、学历和限制词。
- 解析失败时，走当前确定性规则，不中断请求。

- [ ] **Step 4: 运行测试确认 Planner 服务通过**

Run:
`pytest backend/tests/gwy/test_search_query_planner_service.py -q`

Expected: PASS。

- [ ] **Step 5: 提交这一层的基础实现**

```bash
git add backend/app/gwy/services/search_query_planner_service.py backend/app/gwy/prompts/search_query_planner.py backend/tests/gwy/test_search_query_planner_service.py backend/app/gwy/README.md
git commit -m "feat: add shared search query planner"
```

### Task 2: 把所有自然语言搜索入口统一接入 Planner

**Files:**
- Modify: `backend/app/gwy/services/web_research_service.py`
- Modify: `backend/app/gwy/agents/web_verification_agent.py`
- Modify: `backend/app/gwy/agents/position_analysis_agent.py`
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
- Modify: `backend/app/gwy/services/policy_rag_service.py`
- Modify: `backend/app/gwy/mcp_tools/web_server.py`
- Modify: `backend/app/gwy/services/web_mcp_client.py`（如需补充 planner 相关字段透传）
- Modify: `backend/app/gwy/agent_runtime/mcp_tools.py`（如需补充 verify/search 的参数透传说明）
- Modify: `backend/app/gwy/runtime_skills/web-research/SKILL.md`（补充“先规划再搜索”的行为）
- Test: `backend/tests/gwy/test_web_research_service.py`
- Test: `backend/tests/gwy/test_position_analysis_web_evidence.py`
- Test: `backend/tests/gwy/test_agent_runtime_mcp_tools.py`
- Test: `backend/tests/gwy/test_agent_runtime_hooks.py`
- Test: `backend/tests/gwy/test_policy_rag_service.py`（如果 policy 检索也接入统一 planner）

**Interfaces:**
- Consumes:
  - `SearchQueryPlannerService.plan(...)`
  - 现有 `search_service.search(...)`
  - 现有 `PolicyRagService` rewrite / retrieval flow
- Produces:
  - 所有搜索入口都使用统一 `planned_queries`
  - trace 中可见 `original_query`、`primary_query`、`planned_queries`、`required_source_kinds`

- [ ] **Step 1: 先写会失败的集成测试，明确“所有入口都要先规划”**

```python
def test_web_research_service_uses_planner_before_search() -> None:
    ...
    assert result.trace[0]["step"] == "search_query_planned"
    assert result.trace[0]["output"]["primary_query"].startswith("100110001001")
```

```python
def test_autonomous_chat_tool_search_web_uses_planner() -> None:
    ...
    assert any(event["step"] == "search_query_planned" for event in trace)
    assert any("官方公告" in item["query"] for item in tool_calls)
```

```python
def test_position_analysis_web_search_records_planned_queries() -> None:
    ...
    assert any("planned_queries" in event.get("output", {}) for event in trace)
```

- [ ] **Step 2: 运行这些测试确认当前行为还不满足需求**

Run:
`pytest backend/tests/gwy/test_web_research_service.py backend/tests/gwy/test_position_analysis_web_evidence.py backend/tests/gwy/test_agent_runtime_hooks.py -q`

Expected: 至少包含“没有 search_query_planned trace / 没有 planner 输出”的失败。

- [ ] **Step 3: 把 Planner 接到所有搜索入口**

实现要求：
- `WebResearchService.verify(...)` 在 `_queries(...)` 之前先调用 `SearchQueryPlannerService.plan(...)`，用 planner 输出替换当前的原始查询列表。
- `web_verification_agent` 的 `_build_web_search_queries(...)` / `_refine_search_queries(...)` 改为调用 planner，而不是只做字符串拼接。
- `position_analysis_agent` 的补证查询构造改成“先生成缺口意图，再交给 planner 生成正式查询串”。
- `autonomous_chat_agent_service._tool_search_web(...)` 不再直接把用户原始 query 丢给 `WebSearchService.search(...)`，而是先走 planner，再搜索。
- `policy_rag_service` 若保留原有 rewrite node，则把 rewrite 输入统一交给同一个 planner prompt，避免 web / policy 两套写法漂移。
- `mcp_tools/web_server.py` 的 `web_search` / `verify_web_evidence` 入口也要透传 planner 结果，保证 MCP 直连和本地直调一致。

示例实现形态：

```python
plan = self.search_query_planner.plan(
    SearchQueryRequest(
        query=query,
        search_kind="web",
        position=dict(context.state.get("position") or {}),
        planned_queries=list(args.get("planned_queries") or []),
    )
)
queries = [plan.primary_query, *plan.planned_queries]
```

- [ ] **Step 4: 运行集成测试并修正回归**

Run:
`pytest backend/tests/gwy/test_web_research_service.py backend/tests/gwy/test_position_analysis_web_evidence.py backend/tests/gwy/test_agent_runtime_hooks.py backend/tests/gwy/test_agent_runtime_mcp_tools.py -q`

Expected: PASS。

- [ ] **Step 5: 提交这一层的统一接入**

```bash
git add backend/app/gwy/services/web_research_service.py backend/app/gwy/agents/web_verification_agent.py backend/app/gwy/agents/position_analysis_agent.py backend/app/gwy/services/autonomous_chat_agent_service.py backend/app/gwy/services/policy_rag_service.py backend/app/gwy/mcp_tools/web_server.py backend/app/gwy/services/web_mcp_client.py backend/app/gwy/agent_runtime/mcp_tools.py backend/app/gwy/runtime_skills/web-research/SKILL.md backend/tests/gwy/test_web_research_service.py backend/tests/gwy/test_position_analysis_web_evidence.py backend/tests/gwy/test_agent_runtime_mcp_tools.py backend/tests/gwy/test_agent_runtime_hooks.py backend/tests/gwy/test_policy_rag_service.py
git commit -m "feat: route search flows through query planner"
```

### Task 3: 把 trace / hook / 文档补到“看得见原始词和改写词”的程度

**Files:**
- Modify: `backend/app/gwy/services/web_research_service.py`
- Modify: `backend/app/gwy/services/autonomous_chat_agent_service.py`
- Modify: `backend/app/gwy/agents/web_verification_agent.py`
- Modify: `backend/app/gwy/agents/position_analysis_agent.py`
- Modify: `backend/app/gwy/services/policy_rag_service.py`
- Modify: `backend/app/gwy/README.md`
- Modify: `backend/app/gwy/runtime_skills/web-research/SKILL.md`
- Modify: `backend/tests/gwy/test_agent_runtime_hooks.py`

**Interfaces:**
- Consumes:
  - trace event payloads
  - planner output
- Produces:
  - 更具体的 hook 日志，例如：
    - `search_query_planned`
    - `search_query_rewritten`
    - `search_query_fallback`
    - `search_query_executed`

- [ ] **Step 1: 写一个会失败的 trace 断言测试**

```python
def test_web_search_trace_includes_original_and_rewritten_queries() -> None:
    trace = service.verify(...).trace

    assert any(event["step"] == "search_query_planned" for event in trace)
    planned = next(event for event in trace if event["step"] == "search_query_planned")
    assert planned["output"]["original_query"]
    assert planned["output"]["planned_queries"]
    assert planned["output"]["search_kind"] == "web"
```

- [ ] **Step 2: 运行测试，确认当前 trace 还不够细**

Run:
`pytest backend/tests/gwy/test_agent_runtime_hooks.py -q`

Expected: 失败点集中在 trace 缺少 planner 输出字段。

- [ ] **Step 3: 增强各入口的 trace payload**

实现要求：
- 所有搜索入口在发起搜索前，先记录一条 `search_query_planned`，带上：
  - `original_query`
  - `primary_query`
  - `planned_queries`
  - `required_source_kinds`
  - `search_kind`
  - `planner_strategy`（`llm` 或 `fallback_rules`）
- 如果模型输出被丢弃或回退，trace 中要明确标明 `fallback_reason`。
- 子 Agent 结束时的 summary 要把“用了哪个 Planner / 哪些工具 / 哪次搜索重试”写全，不再只写“创建了子 Agent”。
- 主 Agent 的 trace 也要显示具体加载了哪些 skill、具体调用了什么搜索入口，而不是笼统的“加载 skills”。

- [ ] **Step 4: 更新 README 和 runtime skill 文档**

文档需要补充：
- `verify_web_evidence` 和 `web_search` 现在会先经过 Query Planner
- trace 中会出现 `search_query_planned`
- 竞争类问题优先走官方来源，且 planner 会主动补 `官方公告 / site:gov.cn / 招考简章 / 面试名单 / 进面分` 等词

- [ ] **Step 5: 运行最后一轮完整测试并收口**

Run:
`pytest backend/tests/gwy/test_search_query_planner_service.py backend/tests/gwy/test_web_research_service.py backend/tests/gwy/test_position_analysis_web_evidence.py backend/tests/gwy/test_agent_runtime_hooks.py backend/tests/gwy/test_agent_runtime_mcp_tools.py -q`

Expected: PASS。

- [ ] **Step 6: 提交最终收口**

```bash
git add backend/app/gwy/services/web_research_service.py backend/app/gwy/services/autonomous_chat_agent_service.py backend/app/gwy/agents/web_verification_agent.py backend/app/gwy/agents/position_analysis_agent.py backend/app/gwy/services/policy_rag_service.py backend/app/gwy/README.md backend/app/gwy/runtime_skills/web-research/SKILL.md backend/tests/gwy/test_agent_runtime_hooks.py
git commit -m "feat: add query planner traces and docs"
```

## Self-Review

**1. Spec coverage:**  
- 共享 Query Planner：Task 1  
- 全部自然语言搜索入口接入：Task 2  
- trace / hook / 文档增强：Task 3  
- 回退逻辑和测试：Task 1、Task 2、Task 3 都覆盖了

**2. Placeholder scan:**  
没有使用 `TODO`、`TBD`、`implement later` 之类占位词；所有任务都写了具体文件、接口和测试命令。

**3. Type consistency:**  
`SearchQueryRequest` / `SearchQueryPlan` / `SearchQueryPlannerService.plan(...)` 的命名在后续任务中保持一致；各入口都通过同一组字段传递 `original_query`、`primary_query`、`planned_queries` 和 `required_source_kinds`。

