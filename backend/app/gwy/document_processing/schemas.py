from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BlockType(str, Enum):
    TABLE = "table"
    TABLE_ROW = "table_row"
    EXAM_ITEM_MULTIMODAL = "exam_item_multimodal"
    POLICY_QA = "policy_qa"
    POLICY_SECTION = "policy_section"
    SEMANTIC_TEXT = "semantic_text"
    IMAGE_BLOCK = "image_block"


class BaseChunk(BaseModel):
    chunk_id: str
    chunk_type: BlockType
    doc_type: str
    source_file: str
    source_category: str = "official"
    title: str | None = None
    section_path: list[str] = Field(default_factory=list)
    content: str
    page_start: int
    page_end: int
    bbox: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_queries: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class PolicyQAChunk(BaseChunk):
    question: str
    answer: str


class TableChunk(BaseChunk):
    table_title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class TableRowChunk(BaseChunk):
    row_key: str
    columns: list[str] = Field(default_factory=list)


class ExamItemMultimodalChunk(BaseChunk):
    question_type: str | None = None
    stem: str
    options: dict[str, str] = Field(default_factory=dict)
    answer: str | None = None
    explanation: str | None = None
    image_refs: list[str] = Field(default_factory=list)
    ocr_text: str | None = None
    visual_description: str | None = None


class PolicySectionChunk(BaseChunk):
    heading: str | None = None
    clause_id: str | None = None

