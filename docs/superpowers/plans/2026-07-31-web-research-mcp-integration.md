# 网页检索 MCP 统一接入实现计划

> **供 Agent 使用：** 必须使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 按任务执行本计划。每个步骤使用复选框跟踪。

**目标：** 将网页搜索、网页抓取和浏览器/MCP 核验统一接入岗位分析与自主对话两个入口，并产出可引用证据与可统计 trace。

**架构：** 新增 `WebResearchService` 作为唯一网页研究编排边界，复用现有搜索、HTTP 抓取和 Playwright/MCP 服务。自主对话通过 `ToolRegistry` 调用 `verify_web_evidence`，岗位分析复用同一服务；`web-research/SKILL.md` 只负责 Agent 行为规则。

**技术栈：** FastAPI、Python、LangGraph、现有 `ToolRegistry`、`httpx`、Playwright、MCP Streamable HTTP。

## 全局约束

- PostgreSQL 是岗位结构化筛选的事实来源，网页检索不能替代岗位过滤。
- 不新增前端页面，不实现本地 MCP Server。
- 网页搜索摘要必须经过页面抓取或其他方式核验后才能作为引用。
- 只允许访问 `http` 和 `https` URL，并限制查询、页面、结果和证据片段数量。
- trace 中不能保存完整网页正文、凭据或 Authorization 请求头。
- 优先复用现有 `WebSearchService`、`WebFetchService`、`PlaywrightMCPService` 和 `WebVerificationAgent`，不复制第二套抓取逻辑。
- 每个任务先写失败测试，再实现最小代码，测试通过后再进入下一个任务。

---

### 任务 1：定义网页研究数据结构和统一编排服务

**文件：**

- 创建：`backend/app/gwy/services/web_research_service.py`
- 创建：`backend/tests/gwy/test_web_research_service.py`

**接口：**

- 消费：`WebSearchService.search()`、`WebFetchService.fetch()`、`PlaywrightMCPService.read()`。
- 产出：`WebResearchRequest`、`WebEvidence`、`WebResearchResult`、`WebResearchService.verify()`。

- [ ] **步骤 1：先写失败测试**

测试固定查询数量、URL 去重、HTTP 成功结果标准化、空页面浏览器回退和证据不足结果：

```python
def test_verify_web_evidence_normalizes_fetched_results():
    service = WebResearchService(
        search_service=FakeSearchService([{"url": "https://gov.example/a", "title": "官方公告"}]),
        fetch_service=FakeFetchService({"https://gov.example/a": {"url": "https://gov.example/a", "title": "官方公告", "text": "报名条件"}}),
        browser_service=FakeBrowserService({}),
    )

    result = service.verify(WebResearchRequest(query="报名条件"))

    assert result.insufficient_evidence is False
    assert result.evidence[0].source_domain == "gov.example"
    assert result.evidence[0].excerpt == "报名条件"
    assert result.evidence[0].retrieved_via == "http"
    assert "web_verification_completed" in [item["step"] for item in result.trace]


def test_verify_web_evidence_uses_browser_when_http_text_is_empty():
    service = WebResearchService(
        search_service=FakeSearchService([{"url": "https://example.com/js", "title": "动态页面"}]),
        fetch_service=FakeFetchService({"https://example.com/js": {"url": "https://example.com/js", "text": ""}}),
        browser_service=FakeBrowserService({"https://example.com/js": {"url": "https://example.com/js", "text": "动态内容", "retrieved_via": "playwright_local"}}),
    )

    result = service.verify(WebResearchRequest(query="动态页面"))

    assert result.evidence[0].text == "动态内容"
    assert result.evidence[0].retrieved_via == "playwright_local"


def test_verify_web_evidence_rejects_non_http_urls():
    service = WebResearchService(search_service=FakeSearchService([]))

    result = service.verify(WebResearchRequest(query="x", seed_urls=["file:///secret.txt"]))

    assert result.evidence == []
    assert result.insufficient_evidence is True
    assert result.failures[0]["reason"] == "unsupported_url_scheme"
```

- [ ] **步骤 2：运行失败测试**

运行：

```bash
cd backend
pytest tests/gwy/test_web_research_service.py -q
```

预期：失败，提示 `WebResearchService` 或相关数据结构不存在。

- [ ] **步骤 3：实现最小服务**

实现以下职责：

```python
@dataclass(slots=True)
class WebResearchRequest:
    query: str
    position: dict[str, Any] | None = None
    planned_queries: list[str] = field(default_factory=list)
    seed_urls: list[str] = field(default_factory=list)
    top_k: int = 3
    max_queries: int = 3


@dataclass(slots=True)
class WebEvidence:
    title: str | None
    url: str
    final_url: str | None
    source_domain: str | None
    published_at: str | None
    retrieved_at: str
    excerpt: str
    evidence_type: str
    credibility: str
    retrieved_via: str
    text: str = ""


@dataclass(slots=True)
class WebResearchResult:
    evidence: list[WebEvidence]
    failures: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    insufficient_evidence: bool


class WebResearchService:
    def verify(self, request: WebResearchRequest) -> WebResearchResult: ...
```

查询应合并 `planned_queries` 和 `query` 后去重并截断到 `max_queries`；搜索结果按 URL 去重；先 HTTP 抓取，返回空文本时调用浏览器；所有步骤记录稳定 trace；没有有效文本时返回 `insufficient_evidence=True`。

- [ ] **步骤 4：运行测试并确认通过**

运行：

```bash
cd backend
pytest tests/gwy/test_web_research_service.py -q
```

预期：全部通过。

- [ ] **步骤 5：提交**

```bash
git add backend/app/gwy/services/web_research_service.py backend/tests/gwy/test_web_research_service.py
git commit -m "feat: add unified web research service"
```

### 任务 2：增加中文运行时 Skill

**文件：**

- 创建：`backend/app/gwy/runtime_skills/web-research/SKILL.md`
- 修改：`backend/app/gwy/agent_runtime/skills.py`，仅在当前加载器需要显式目录配置时修改
- 创建或修改：`backend/tests/gwy/test_runtime_skills.py`

**接口：**

- 消费：`load_skill` 的运行时 Skill 加载约定。
- 产出：Skill 名称 `web-research` 及其中文流程规则。

- [ ] **步骤 1：先写失败测试**

```python
def test_web_research_runtime_skill_is_discoverable():
    registry = SkillRegistry.from_path(Path("app/gwy/runtime_skills"))

    skill = registry.get("web-research")

    assert skill is not None
    assert "网页检索" in skill.content
    assert "PostgreSQL" in skill.content
```

- [ ] **步骤 2：运行失败测试**

```bash
cd backend
pytest tests/gwy/test_runtime_skills.py::test_web_research_runtime_skill_is_discoverable -q
```

预期：失败，提示找不到 `web-research`。

- [ ] **步骤 3：创建 Skill 文档**

文档必须使用中文并写明：触发条件、查询规划、官方来源优先级、搜索/抓取/浏览器回退顺序、证据字段、失败时返回证据不足、禁止用网页检索替代 PostgreSQL 岗位筛选，以及 trace 要求。

- [ ] **步骤 4：运行测试并确认通过**

```bash
cd backend
pytest tests/gwy/test_runtime_skills.py -q
```

预期：全部通过。

- [ ] **步骤 5：提交**

```bash
git add backend/app/gwy/runtime_skills/web-research/SKILL.md backend/app/gwy/agent_runtime/skills.py backend/tests/gwy/test_runtime_skills.py
git commit -m "feat: add web research runtime skill"
```

### 任务 3：修正远程 MCP 工具选择和参数构造

**文件：**

- 修改：`backend/app/gwy/services/playwright_mcp_service.py`
- 修改或创建：`backend/tests/gwy/test_playwright_mcp_service.py`

**接口：**

- 消费：远程 MCP `list_tools()` 返回的工具名称、描述和 `inputSchema`。
- 产出：兼容 URL 输入的工具名称、按 schema 构造的参数和结构化失败 trace。

- [ ] **步骤 1：先写失败测试**

```python
def test_select_mcp_tool_prefers_required_url_schema():
    service = PlaywrightMCPService(enabled=False)
    tools = [
        FakeTool("click", "click an element", {"type": "object", "properties": {"selector": {}}}),
        FakeTool("read_page", "read a page", {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}),
    ]

    assert service._select_mcp_tool_name(tools) == "read_page"
    assert service._build_mcp_arguments(tools, "read_page", "https://example.com") == {"url": "https://example.com"}


def test_select_mcp_tool_returns_none_without_compatible_url_input():
    service = PlaywrightMCPService(enabled=False)
    tools = [FakeTool("click", "click an element", {"type": "object", "properties": {"selector": {}}})]

    assert service._select_mcp_tool_name(tools) is None
```

- [ ] **步骤 2：运行失败测试**

```bash
cd backend
pytest tests/gwy/test_playwright_mcp_service.py -q
```

预期：失败，因为当前实现会按名称关键词或第一个工具选择。

- [ ] **步骤 3：实现 schema-aware 选择**

实现顺序：先检查 `inputSchema.properties` 和 `required` 中的 `url`、`target`、`page_url`、`href`、`input`；再检查工具描述是否包含页面读取/导航能力；没有兼容字段时返回 `None`，禁止回退到第一个工具。参数构造只写入 schema 中存在的字段。

- [ ] **步骤 4：运行测试并确认通过**

```bash
cd backend
pytest tests/gwy/test_playwright_mcp_service.py -q
```

预期：全部通过，且现有本地 Playwright 回退测试不回归。

- [ ] **步骤 5：提交**

```bash
git add backend/app/gwy/services/playwright_mcp_service.py backend/tests/gwy/test_playwright_mcp_service.py
git commit -m "fix: select remote MCP page tools by schema"
```

### 任务 4：将网页工具注册到自主对话 Agent

**文件：**

- 修改：`backend/app/gwy/services/autonomous_chat_agent_service.py`
- 修改：`backend/app/gwy/mcp_tools/web_tools.py`，保留为薄 wrapper 或改为调用统一服务
- 修改：`backend/tests/gwy/test_autonomous_chat_agent_service.py`，若已有同类测试则扩展现有文件

**接口：**

- 消费：`WebResearchService.verify(WebResearchRequest(...))`。
- 产出：ToolRegistry 中的 `search_web`、`fetch_web_page`、`read_web_page` 和 `verify_web_evidence`。

- [ ] **步骤 1：先写失败测试**

```python
def test_tool_registry_contains_web_research_tools(agent_service):
    registry = agent_service._build_tool_registry()

    assert registry.get("search_web") is not None
    assert registry.get("fetch_web_page") is not None
    assert registry.get("read_web_page") is not None
    assert registry.get("verify_web_evidence") is not None
```

再增加 handler 测试，断言 `verify_web_evidence` 将 query 传给统一服务，并把 evidence、citation_count、failures 和 trace 放入返回值。

- [ ] **步骤 2：运行失败测试**

```bash
cd backend
pytest tests/gwy/test_autonomous_chat_agent_service.py -q
```

预期：失败，因为 ToolRegistry 尚未注册网页工具。

- [ ] **步骤 3：注册工具并写 handler**

在 `_build_tool_registry()` 中注册参数 schema。`verify_web_evidence` handler 只负责构造 `WebResearchRequest`、调用 `WebResearchService.verify()`、记录工具调用事件并返回摘要；不把完整网页文本写入 Agent trace。

- [ ] **步骤 4：运行测试并确认通过**

```bash
cd backend
pytest tests/gwy/test_autonomous_chat_agent_service.py -q
```

预期：全部通过，已有政策和岗位工具测试不回归。

- [ ] **步骤 5：提交**

```bash
git add backend/app/gwy/services/autonomous_chat_agent_service.py backend/app/gwy/mcp_tools/web_tools.py backend/tests/gwy/test_autonomous_chat_agent_service.py
git commit -m "feat: register web research tools in chat agent"
```

### 任务 5：让岗位分析复用统一网页研究服务

**文件：**

- 修改：`backend/app/gwy/agents/web_verification_agent.py`
- 修改：`backend/app/gwy/agents/position_analysis_agent.py`，仅调整依赖注入和结果接收
- 修改：`backend/tests/gwy/test_web_retrieval_services.py` 或现有岗位分析测试文件

**接口：**

- 消费：岗位上下文、历史摘要、研究目标和查询提示。
- 产出：统一的 `WebResearchResult`，并保留岗位分析所需的历史核验字段和 trace。

- [ ] **步骤 1：先写失败测试**

```python
def test_position_web_verification_uses_shared_research_service():
    research_service = FakeWebResearchService(result=expected_result)
    agent = WebVerificationAgent(research_service=research_service)

    result = agent.run(
        position={"job_title": "岗位"},
        history_summary={},
        history_records=[],
        scope={"year": 2026},
        planned_queries=["岗位 招录"],
    )

    assert research_service.requests[0].query == "岗位 招录"
    assert result["web_results"]
    assert result["trace"]
```

- [ ] **步骤 2：运行失败测试**

```bash
cd backend
pytest tests/gwy/test_web_retrieval_services.py -q
```

预期：失败，因为 `WebVerificationAgent` 当前直接执行搜索和抓取循环。

- [ ] **步骤 3：委托统一服务**

保留现有查询计划和岗位分析状态格式，将 `_node_search` 的搜索、抓取、浏览器回退和证据标准化委托给 `WebResearchService`；把统一结果映射回 `web_results`、`web_search_attempts` 和 `trace`，确保报告生成器不需要改变输入协议。

- [ ] **步骤 4：运行测试并确认通过**

```bash
cd backend
pytest tests/gwy/test_web_retrieval_services.py tests/gwy/test_position_analysis_agent.py -q
```

预期：全部通过，岗位分析中的 PostgreSQL 检索和政策证据流程不回归。

- [ ] **步骤 5：提交**

```bash
git add backend/app/gwy/agents/web_verification_agent.py backend/app/gwy/agents/position_analysis_agent.py backend/tests/gwy/test_web_retrieval_services.py
git commit -m "refactor: share web research path with position analysis"
```

### 任务 6：补充安全限制、集成测试和验证

**文件：**

- 修改：`backend/app/core/config.py`，增加网页研究限制配置（若现有配置没有等价项）
- 修改：`backend/app/gwy/services/web_research_service.py`
- 创建或修改：`backend/tests/gwy/test_web_research_integration.py`
- 修改：`backend/app/gwy/runtime_skills/web-research/SKILL.md`

**接口：**

- 消费：统一网页研究服务和两个入口的 ToolRegistry。
- 产出：URL 校验、查询/页面/片段限制、完整 trace 和端到端可验证结果。

- [ ] **步骤 1：先写失败测试**

```python
def test_web_research_rejects_file_and_private_urls():
    result = service.verify(WebResearchRequest(query="x", seed_urls=["file:///tmp/a", "http://127.0.0.1:8000"]))

    assert result.evidence == []
    assert all(item["reason"] in {"unsupported_url_scheme", "blocked_private_host"} for item in result.failures)


def test_web_research_trace_contains_terminal_event():
    result = service.verify(WebResearchRequest(query="官方公告"))

    assert result.trace[-1]["step"] == "web_verification_completed"
    assert "duration_ms" in result.trace[-1]
```

- [ ] **步骤 2：运行失败测试**

```bash
cd backend
pytest tests/gwy/test_web_research_integration.py -q
```

预期：失败，因为安全限制和统一终态 trace 尚未完整实现。

- [ ] **步骤 3：实现限制和集成验证**

增加 URL scheme/私有地址校验、查询/结果/页面/片段上限和统一失败格式；更新 Skill 文档，使其与实际返回字段和 trace 名称一致；用 fake 搜索、抓取和浏览器后端验证自主对话与岗位分析都能得到同一证据格式。

- [ ] **步骤 4：运行完整验证**

```bash
cd backend
bash ./scripts/test.sh
bash ./scripts/lint.sh
```

预期：后端测试和 lint 全部通过。

- [ ] **步骤 5：提交**

```bash
git add backend/app/core/config.py backend/app/gwy/services/web_research_service.py backend/app/gwy/runtime_skills/web-research/SKILL.md backend/tests/gwy/test_web_research_integration.py
git commit -m "test: verify web research MCP integration"
```

## 计划自检

- 设计中的 Skill、统一服务、ToolRegistry、MCP schema 匹配、两个入口接入、安全限制、trace 和测试均有对应任务。
- 没有使用 `TODO`、`TBD` 或未定义的后续步骤作为实现要求。
- `WebResearchRequest`、`WebEvidence`、`WebResearchResult` 和 `WebResearchService.verify()` 在任务 1 定义，后续任务复用同一接口。
- 任务顺序保证先有可测试的统一服务，再接入自主对话和岗位分析，最后补安全与完整验证。
