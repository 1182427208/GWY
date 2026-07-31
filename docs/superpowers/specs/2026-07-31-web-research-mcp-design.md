# 网页检索 MCP 统一接入设计

## 目标

让岗位分析流程和自主对话流程都能够使用网页搜索与网页核验，同时继续保持 PostgreSQL 作为岗位结构化筛选的事实来源。网页检索必须产出可复用的证据和 trace，而不是只返回未经核验的网页文本。

## 范围

纳入范围：

- 新增 `backend/app/gwy/runtime_skills/web-research/SKILL.md`。
- 引入统一的网页研究编排服务。
- 将网页研究能力注册到现有 `ToolRegistry`。
- 复用 `WebSearchService`、`WebFetchService` 和 `PlaywrightMCPService` 作为执行后端。
- 让自主对话和岗位分析使用同一套网页研究流程。
- 统一证据记录和 trace 事件格式。
- 将远程 MCP 工具选择改为基于 schema 的匹配。
- 增加针对性的单元测试和集成测试。

不纳入范围：

- 用网页搜索或 RAG 替代 PostgreSQL 岗位筛选。
- 新增前端页面。
- 实现本地 MCP Server。
- 批量爬取任意网站或建立通用网页索引。
- 将搜索摘要直接作为权威证据。

## 当前状况

仓库中已经存在：

- `WebSearchService`：访问搜索服务。
- `WebFetchService`：通过 HTTP 或可选的 fetch MCP 抓取网页。
- `PlaywrightMCPService`：访问远程 MCP 浏览器，并在必要时回退到本地 Playwright。
- `WebVerificationAgent`：岗位分析中已经使用，用于查询规划、搜索、抓取、浏览器回退和 trace 记录。
- `backend/app/gwy/mcp_tools/web_tools.py`：提供了简单 wrapper，但尚未注册到 `ToolRegistry`。
- `runtime_skills/policy-rag` 和 `runtime_skills/position-planning`：通过运行时 `load_skill` 工具加载。

当前主要问题是编排和注册不统一：岗位分析流程直接持有网页服务，自主对话流程无法请求网页核验工具。因此 MCP wrapper 没有统一入口，也没有统一的调用观测路径。

## 建议架构

```text
运行时 Skill：web-research
            |
自主对话 ------> ToolRegistry：verify_web_evidence
            |                         |
岗位分析 ------> WebResearchService
                                      |
              +-----------------------+-----------------------+
              |                       |                       |
       WebSearchService       WebFetchService        PlaywrightMCPService
              |                       |                       |
        搜索服务提供方        HTTP/fetch MCP       远程 MCP/本地 Playwright
```

### 运行时 Skill

新增的 `web-research/SKILL.md` 应明确：

- 触发条件：本地历史数据缺失、需要核验最新官方政策、用户明确要求查询网页，或本地证据不足。
- 必须执行的步骤：规划查询词、搜索、去重、抓取、必要时浏览器回退、提取证据、评估来源质量、记录 trace。
- 来源优先级：政府和招录主管部门网站优先，其次是官方公告及 PDF 附件，其他来源只能作为辅助证据。
- 证据要求：URL、最终 URL、标题、域名、抓取时间、证据片段、证据类型、可信度和获取方式。
- 失败行为：明确报告证据缺失，不能根据空结果或失败结果推断资格、时间和分数线。
- 网页研究只能补充证据，不能替代结构化 PostgreSQL 岗位筛选。

Skill 是 Agent 的行为约束，不包含网络执行逻辑，也不能替代 `ToolRegistry` 注册。

### WebResearchService

该服务是两个调用入口共享的网页研究编排边界。请求中应包含用户问题、可选的岗位上下文、查询提示、来源约束、结果数量限制和 trace 上下文。服务返回标准化证据、来源质量判断、失败信息和 trace 事件。

服务流程：

1. 生成数量受限的目标查询词。
2. 使用固定结果预算执行搜索。
3. 按规范化 URL 和标题去重。
4. 优先官方域名，并尽早过滤不可用结果。
5. 通过 HTTP 抓取候选网页。
6. 当 HTTP 内容为空、依赖 JavaScript 或页面结构不可用时，才使用浏览器渲染。
7. 围绕目标提取长度受限的证据片段。
8. 标记来源质量和证据完整性。
9. 返回可用于报告的引用和可用于回放/调试的 trace。

现有 `WebVerificationAgent` 应将搜索阶段委托给该服务，或在图流程层调用该服务，不能继续维护另一套独立的抓取和回退逻辑。

### ToolRegistry 接入

在现有 Agent runtime 中注册以下工具：

- `search_web`：供内部受控使用的底层搜索工具。
- `fetch_web_page`：供内部受控使用的底层网页抓取工具。
- `read_web_page`：供内部受控使用的浏览器/MCP 渲染工具。
- `verify_web_evidence`：面向 Agent 的主要组合工具。

自主对话的主流程应调用 `verify_web_evidence`，不应自行串联三个底层工具。岗位分析流程也应通过同一服务或同一组合边界调用，从而共享标准化、限制、回退和 trace 逻辑。

`verify_web_evidence` 的返回结构至少应包含：

```json
{
  "evidence": [],
  "citation_count": 0,
  "insufficient_evidence": false,
  "failures": [],
  "trace": []
}
```

### 证据结构

每条证据至少包含：

```text
title
url
final_url
source_domain
published_at
retrieved_at
excerpt
evidence_type
credibility
retrieved_via
```

如果无法核验发布时间，`published_at` 可以为空。`credibility` 必须根据来源和提取状态计算，不能只根据搜索排名判断。

### 远程 MCP 工具选择

`PlaywrightMCPService` 不应继续主要依赖工具名称关键词，也不应在没有匹配结果时默认调用工具列表中的第一个工具。选择逻辑应当：

1. 读取远程工具的名称、描述和输入 schema。
2. 筛选描述为页面读取/导航，或存在 URL 类输入的工具。
3. 优先选择必填参数中包含 `url`、`target`、`page_url` 或等价字段的工具。
4. 根据选中工具的 schema 构造参数。
5. 找不到兼容工具时返回结构化失败信息。

选中的远程工具名称和 schema 匹配结果必须写入 trace。远程 MCP 未配置、不可用或不兼容时，继续回退到本地 Playwright。

## 安全性和可靠性

- 只允许访问 `http` 和 `https` URL。
- 限制请求数量、页面数量、查询数量和证据片段长度。
- 保留重定向后的最终 URL。
- 在配置允许时，浏览器访问前执行域名允许/拒绝规则。
- 不记录凭据、Authorization 请求头或完整网页内容。
- 在编排边界捕获后端异常，并返回明确的失败信息。
- 将网页证据与结构化岗位事实分开保存。
- 搜索摘要必须经过网页抓取或其他方式核验后，才能作为引用。

## Trace 约定

统一链路应输出以下稳定的 trace 步骤：

- `web_query_planned`
- `web_search_started`
- `web_search_completed`
- `web_page_fetch_started`
- `web_page_fetch_completed`
- `web_browser_fallback`
- `web_evidence_extracted`
- `web_verification_completed`

每个步骤应包含状态、可用时的耗时、受限的输入/输出摘要、获取方式，以及失败时的原因。完整网页正文不能写入 trace。

## 测试策略

单元测试应覆盖：

- 查询数量限制和去重。
- 官方域名优先级。
- HTTP 成功、空页面回退、PDF 处理和抓取失败。
- 浏览器回退选择。
- 远程 MCP schema 匹配和不兼容 schema 失败。
- 证据标准化和缺失发布时间的处理。
- URL 校验和配置限制。

集成测试应验证：

- 自主对话能够注册并调用 `verify_web_evidence`。
- 岗位分析使用统一的网页编排路径。
- 成功和失败检索都会生成 trace。
- 网页证据可以进入报告，同时不改变 PostgreSQL 岗位筛选逻辑。

## 验收标准

- 两个入口都可以调用同一个网页核验能力。
- 至少有一个端到端测试证明搜索结果能够转化为标准化引用，或明确返回证据不足。
- MCP 和本地 Playwright 回退路径可以通过 `retrieved_via` 和 trace 区分。
- Agent 不需要了解具体由哪个后端执行网页检索。
- 可以通过现有 trace 统计运行时各工具的真实调用次数。
