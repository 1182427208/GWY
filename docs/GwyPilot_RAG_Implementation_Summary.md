# GwyPilot Policy Agentic RAG 说明

## 1. 模型选型
- 问答模型: `Qwen/Qwen2.5-72B-Instruct-128K`
- Embedding 模型: `Qwen/Qwen3-Embedding-8B`
- Rerank 模型: `Qwen/Qwen3-Reranker-8B`
- 多模态图片摘要: 复用 `.env` 中的 `SILICONFLOW_CHAT_MODEL=Qwen/Qwen3-VL-32B-Instruct`
- 统一通过 SiliconFlow OpenAI-compatible API 调用，`base_url=https://api.siliconflow.cn/v1`

## 2. Milvus Collection 设计
- 共享政策库集合: `gwy_policy_rag_chunks`
- 支持的 chunk 类型:
  - `text_qa`
  - `text_clause`
  - `text_module`
  - `fallback_paragraph`
  - `image_summary`
  - `table_summary`
  - `table_row`
- 关键字段:
  - `content`
  - `year`
  - `exam_type`
  - `province`
  - `doc_group`
  - `doc_type`
  - `doc_title`
  - `section`
  - `question`
  - `source_file`
  - `page_start`
  - `page_end`
  - `asset_type`
  - `image_id`
  - `image_path`
  - `table_id`
  - `row_id`
  - `table_image_path`
  - `bbox_list`
  - `linked_image_ids`
  - `linked_table_ids`
  - `metadata_json`
- 当前已完成一次全量重导入: `34` 个 PDF，`986` 个 chunk

## 3. PDF 解析流程
- `backend/app/gwy/document/pdf_loader.py`
  - 使用 LlamaIndex + PyMuPDF 读取 PDF 的文本页
  - 输出按页组织的 `[{page, text}]`
- `backend/app/gwy/document/layout_analyzer.py`
  - 先做版面分析，区分 `text | title | header | footer | image | table`
  - 为每个 block 记录 `page` 和 `bbox`
- `backend/app/gwy/document/image_extractor.py`
  - 提取图片区域，保存原图到 `data/processed/assets/images/...`
  - 调用多模态模型生成图片摘要，失败时回退到 `pending_multimodal_summary`
- `backend/app/gwy/document/table_extractor.py`
  - 使用 `pdfplumber` 提取表格
  - 输出 Markdown Table、行级文本、表格图片映射
- `backend/app/gwy/document/cross_page_table_merger.py`
  - 通过页码连续性、列数、表头相似度合并跨页表格

## 4. 差异化切分策略
- 政策问答 / 技术问答 / 考务问答
  - 优先按问答对切分
  - chunk_type: `text_qa`
- 招考公告
  - 按“一、二、三、”“（一）（二）”等政策条款切分
  - chunk_type: `text_clause`
- 公共科目 / 专业科目考试大纲
  - 按科目、模块切分
  - chunk_type: `text_module`
- 专业目录
  - 按专业大类 / 学科层次 / 专业条目组织
- fallback
  - 仅在结构无法识别时使用递归段落切分
  - chunk_type: `fallback_paragraph`
- 所有文本 chunk 都保留:
  - `year`
  - `exam_type`
  - `province`
  - `doc_group`
  - `doc_type`
  - `doc_title`
  - `section`
  - `question`
  - `page_start`
  - `page_end`
  - `source_file`
  - `bbox_list`
  - `linked_image_ids`
  - `linked_table_ids`

## 5. Agentic RAG 检索流程
1. Intent Routing
2. Query Rewrite / Multi-query
3. Metadata Filter
4. Milvus Vector Search
5. Hybrid Retrieval
6. RRF Fusion
7. Qwen3-Reranker
8. Context Builder
9. Answer Generation
10. Citation Guard
11. Freshness Guard

## 6. 核心实现方式
- Intent Routing
  - 通过规则与文档类型映射识别问题意图
- Query Rewrite
  - 生成 2~3 个标准化检索 query
- Metadata Filter
  - 优先按 `year=2026`、`exam_type=national`、`doc_group`、`doc_type` 过滤
- RRF
  - 合并原 query + rewrite query 的多路召回结果
- Rerank
  - 用 Qwen3-Reranker 对融合结果重新排序
- Citation Guard
  - 无可靠证据时返回“当前知识库未找到明确依据”
- 当前检索实现
  - 已有 Milvus 向量检索
  - 也保留了简化版 BM25/lexical scoring，后续可替换为更强的外部 hybrid retrieval

## 7. 对话系统、多会话、短期记忆
- 会话表: `gwy_chat_session`
- 消息表: `gwy_chat_message`
- 缓存表: `gwy_rag_cache_entry`
- 短期记忆表: `gwy_conversation_memory`
- Redis 优先，Redis 不可用时回退 PostgreSQL
- 会话仅保存摘要、引用和必要 trace，不无限堆积原始检索结果

## 8. 知识源展示
- 前端在 `/gwy/chat` 展示 citations
- 文本来源展示:
  - `source_file`
  - `doc_title`
  - `section`
  - `page_start/page_end`
  - `content_excerpt`
- 图片来源展示:
  - `image_id`
  - `image_path`
  - `summary`
  - `ocr_text`
- 表格来源展示:
  - `table_id`
  - `row_id`
  - `markdown_content`
  - `table_image_path`

## 9. 调试与验收
- chunk debug:
  - `data/processed/chunks_debug/*.chunks.jsonl`
  - `data/processed/chunks_debug/*.chunks.csv`
  - `data/processed/chunks_preview/*.preview.html`
- document debug:
  - `data/processed/debug/layout_blocks.jsonl`
  - `data/processed/debug/image_assets.jsonl`
  - `data/processed/debug/tables_debug.jsonl`
  - `data/processed/debug/table_rows_debug.csv`
  - `data/processed/debug/chunks_with_assets.jsonl`
- 当前导入结果:
  - `34` 个 PDF
  - `986` 个 chunk
  - `0` 个失败文件

## 10. 当前限制
- 扫描版 PDF 仍未做 OCR
- 图片摘要依赖多模态模型，若不可用会降级为 pending
- 表格抽取对极复杂版式仍可能产生短 chunk 或长 chunk
- 现阶段重点是 RAG 基础设施，不包含岗位推荐 Agent、飞书、MiniMind、浏览器爬虫

## 11. 后续优化方向
- 接入更强的 BM25 / Elasticsearch hybrid retrieval
- 增强表格跨页合并和表头识别
- 补充 OCR 与图片中文字提取
- 增加更细粒度的 citation span 和证据定位
- 做离线评测集和检索质量回归测试

## 12. 简历可写点
- 基于 LangGraph 构建政策类 Agentic RAG 主流程
- 使用 Milvus + Qwen Embedding + Qwen Reranker 搭建政策知识检索链路
- 用 LlamaIndex / PyMuPDF / pdfplumber 实现 PDF 版面分析、图片摘要索引和表格结构化抽取
- 实现多会话、短期记忆、Redis/PostgreSQL 双层缓存
- 提供带来源定位的 citations 和可调试的 chunk / layout / table / image 证据链
## 13. 独立岗位推荐页
- 新增前端路由 `/gwy/positions`，与 `/gwy/chat` 分离。
- 左侧菜单新增“岗位推荐”入口，方便用户从聊天和岗位筛选之间切换。
- 页面采用“筛选条件 + 岗位表格 + 选中岗位分析”三栏结构，支持：
  - 专业、学历、学位、政治面貌、地区、部门、岗位关键词筛选
  - PostgreSQL 岗位表服务端分页查询
  - 当前页勾选、跨页保留已选项
  - 对已选岗位执行匹配分析

## 14. 新增岗位接口
- `GET /api/v1/gwy/positions`
  - 基于 PostgreSQL `gwy_position` 表返回分页岗位列表。
  - 专业筛选使用专业族模糊扩展，避免 `工学` 只能命中字面“工学”的问题。
- `POST /api/v1/gwy/positions/analyze`
  - 对选中岗位执行匹配分析。
  - 输出 `analysis`、`summary`、`recommendations`、`selected_positions` 和 `retrieval_trace`。
- 前端不再把岗位推荐逻辑塞进对话页，岗位筛选和政策问答保持分工清晰。
