---
name: web-research
description: 使用网页搜索、官方页面和浏览器核验补充岗位与政策证据。
---

# 网页检索与核验

## 适用场景

- 本地岗位历史数据缺失，需要补充招录人数、进面名单或竞争信息。
- 需要核验最新的官方公告、报名条件、考试时间或政策变化。
- 用户明确要求查询网页信息。
- PostgreSQL 和 Milvus 中没有足够证据支撑结论。

网页检索只负责补充证据，不能替代 PostgreSQL 的岗位结构化筛选，也不能绕过岗位硬条件判断。

## 标准流程

1. 根据岗位、年份和缺失字段生成有限数量的查询词。
2. 调用网页搜索并按 URL 去重。
3. 优先选择政府部门、招录机关和官方公告来源。
4. 先通过 HTTP 抓取页面；页面为空、依赖 JavaScript 或正文过短时，才使用浏览器/MCP 渲染。
5. 从已抓取页面提取有限长度的证据片段。
6. 记录来源、获取方式、时间和可信度。
7. 证据不足时明确返回“未找到足够证据”，不能补写或猜测结论。

## 来源规则

- `.gov.cn`、政府部门和招录机关官网优先。
- 官方公告 PDF 可以作为正式证据，但必须记录原始 URL。
- 搜索摘要不能直接作为引用，必须抓取或渲染原页面。
- 普通商业网站、论坛和聚合站点只能作为辅助线索，不能单独支撑资格、时间、分数线等关键结论。

## 证据字段

每条证据至少包含：

- `title`
- `url`
- `final_url`
- `source_domain`
- `published_at`
- `retrieved_at`
- `excerpt`
- `evidence_type`
- `credibility`
- `retrieved_via`

无法核验发布时间时，`published_at` 可以为空。

## 失败处理

- 搜索失败、页面抓取失败或浏览器不可用时，返回失败原因和已有证据。
- 远程 MCP 不可用时回退本地 Playwright；本地浏览器也失败时返回证据不足。
- 不访问 `file`、内网、回环地址或私有地址。
- trace 只记录查询、结果数量、来源、耗时和失败原因，不记录完整网页正文或敏感请求头。

## 必须记录的 trace

- `web_query_planned`
- `web_search_started`
- `web_search_completed`
- `web_page_fetch_started`
- `web_page_fetch_completed`
- `web_browser_fallback`
- `web_evidence_extracted`
- `web_verification_completed`
