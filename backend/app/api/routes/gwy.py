from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.core.db import engine
from app.gwy.agents.feishu_push_agent import FeishuPushAgent
from app.gwy.document.pdf_loader import load_pdf_pages
from app.gwy.evals.service import record_online_evaluation
from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.multimodal_service import MultimodalSummaryService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.llm.siliconflow_client import SiliconFlowClient
from app.gwy.models import (
    GwyChatAttachment,
    GwyChatMessage,
    GwyChatSession,
    GwyUserProfile,
)
from app.gwy.prompts.policy_rag import (
    DIRECT_ANSWER_SYSTEM_PROMPT,
    POLICY_RAG_SYSTEM_PROMPT,
)
from app.gwy.services.autonomous_chat_agent_service import AutonomousChatAgentService
from app.gwy.services.chat_session_service import ChatSessionService
from app.gwy.services.chunk_debug_service import ChunkDebugService
from app.gwy.services.long_term_memory_service import LongTermMemoryService
from app.gwy.services.policy_ingestion_service import PolicyIngestionService
from app.gwy.services.policy_rag_service import PolicyRagService
from app.gwy.services.position_catalog_service import (
    PositionCatalogService,
    PositionListFilters,
)
from app.gwy.services.study_plan_service import StudyPlanService
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore
from app.models import Message

router = APIRouter(prefix="/gwy", tags=["gwy"])
logger = logging.getLogger(__name__)

_STREAM_FLUSH_PUNCTUATION = set("。！？；，、\n")
_PIPELINE_STAGE_LABELS = {
    "route_intent": "意图识别",
    "position_recommendation": "岗位推荐",
    "rewrite_queries": "问题改写",
    "retrieve": "知识检索",
    "fuse_and_rerank": "融合重排",
    "direct_answer": "直接回答",
    "answer": "回答生成",
    "finalize": "会话收尾",
}


class PolicyImportRequest(BaseModel):
    path: str
    owner_user_id: UUID | None = None
    collection_name: str | None = None


class PolicyImportResponse(BaseModel):
    success: bool
    file_count: int
    chunk_count: int
    failed_files: list[str]
    chunk_stats: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    debug_artifacts: dict[str, str | None] = Field(default_factory=dict)
    layout_stats: dict[str, Any] | None = None


class PolicySearchRequest(BaseModel):
    query: str
    year: int | None = None
    exam_type: str | None = None
    doc_group: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    use_rerank: bool = True


class PolicySearchResult(BaseModel):
    content: str
    score: float
    rerank_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicySearchResponse(BaseModel):
    results: list[PolicySearchResult]


class PositionRecommendationProfile(BaseModel):
    name: str | None = None
    nickname: str | None = None
    major: str | None = None
    education: str | None = None
    degree: str | None = None
    political_status: str | None = None
    is_fresh_graduate: bool | None = None
    grassroots_experience_years: int | None = None
    target_regions: list[str] = Field(default_factory=list)
    avoid_conditions: list[str] = Field(default_factory=list)
    desired_departments: list[str] = Field(default_factory=list)
    desired_positions: list[str] = Field(default_factory=list)
    excluded_positions: list[str] = Field(default_factory=list)
    notes: str | None = None


class UserProfileResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str | None = None
    nickname: str | None = None
    education: str | None = None
    degree: str | None = None
    major: str | None = None
    political_status: str | None = None
    is_fresh_graduate: bool = False
    grassroots_experience_years: int | None = None
    target_regions: list[str] = Field(default_factory=list)
    avoid_conditions: list[str] = Field(default_factory=list)
    desired_departments: list[str] = Field(default_factory=list)
    desired_positions: list[str] = Field(default_factory=list)
    excluded_positions: list[str] = Field(default_factory=list)
    daily_study_hours: int | None = None
    notes: str | None = None
    feishu_webhook_url: str | None = None


class UserProfileUpdateRequest(BaseModel):
    name: str | None = None
    nickname: str | None = None
    education: str | None = None
    degree: str | None = None
    major: str | None = None
    political_status: str | None = None
    is_fresh_graduate: bool | None = None
    grassroots_experience_years: int | None = None
    target_regions: list[str] | None = None
    avoid_conditions: list[str] | None = None
    desired_departments: list[str] | None = None
    desired_positions: list[str] | None = None
    excluded_positions: list[str] | None = None
    daily_study_hours: int | None = None
    notes: str | None = None
    feishu_webhook_url: str | None = None


class FeishuWebhookTestRequest(BaseModel):
    webhook_url: str | None = None


class FeishuWebhookTestResponse(BaseModel):
    status: str
    detail: str
    response_json: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class PositionListItem(BaseModel):
    id: UUID
    department_code: str | None = None
    department_name: str | None = None
    office_name: str | None = None
    institution_type: str | None = None
    job_title: str | None = None
    position_attribute: str | None = None
    position_distribution: str | None = None
    position_desc: str | None = None
    position_code: str | None = None
    institution_level: str | None = None
    exam_category: str | None = None
    recruit_count: int | None = None
    major_requirement: str | None = None
    education_requirement: str | None = None
    degree_requirement: str | None = None
    political_status_requirement: str | None = None
    grassroots_years_requirement: str | None = None
    grassroots_project_experience: str | None = None
    professional_test_in_interview: str | None = None
    interview_ratio: str | None = None
    work_location: str | None = None
    household_registration_location: str | None = None
    remarks: str | None = None
    department_website: str | None = None
    contact_phone_1: str | None = None
    contact_phone_2: str | None = None
    contact_phone_3: str | None = None
    source_file: str | None = None
    source_sheet: str | None = None
    source_row_number: int | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class PositionListResponse(BaseModel):
    data: list[PositionListItem]
    count: int
    page: int
    page_size: int
    filters: dict[str, Any] = Field(default_factory=dict)


class PositionAnalyzeRequest(BaseModel):
    position_ids: list[UUID] = Field(default_factory=list)
    query: str = ""
    top_k: int = Field(default=10, ge=1, le=20)
    position_profile: PositionRecommendationProfile | None = None
    enable_evaluation: bool = False


class PositionAnalyzeRecord(BaseModel):
    position_id: str | None = None
    department_name: str | None = None
    office_name: str | None = None
    job_title: str | None = None
    position_code: str | None = None
    work_location: str | None = None
    household_registration_location: str | None = None
    education_requirement: str | None = None
    degree_requirement: str | None = None
    major_requirement: str | None = None
    political_status_requirement: str | None = None
    grassroots_years_requirement: str | None = None
    recruit_count: int | None = None
    remarks: str | None = None
    department_website: str | None = None
    contact_phone_1: str | None = None
    contact_phone_2: str | None = None
    contact_phone_3: str | None = None
    score: float | None = None
    recommend_level: str | None = None
    risk_level: str | None = None
    need_manual_confirm: bool | None = None
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)


class TextToSpeechRequest(BaseModel):
    text: str
    voice: str | None = None
    hard_filter_passed: bool = False
    hard_filter_reasons: list[str] = Field(default_factory=list)
    hard_filter_risks: list[str] = Field(default_factory=list)


class PositionAnalyzeResponse(BaseModel):
    analysis: str
    summary: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    selected_positions: list[PositionAnalyzeRecord] = Field(default_factory=list)
    retrieval_trace: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_run_id: UUID | None = None


class PositionPageSheetState(BaseModel):
    filters: dict[str, str] = Field(default_factory=dict)
    sortKey: str = "source_row_number"
    sortDirection: Literal["asc", "desc"] = "asc"
    pageNumber: int = 1
    pageSize: int = 100
    scrollTop: int = 0
    scrollLeft: int = 0


class PositionPageSavedSnapshot(BaseModel):
    savedAt: str = ""
    rowCount: int = 0
    rowIds: list[str] = Field(default_factory=list)
    filters: dict[str, str] = Field(default_factory=dict)
    sortKey: str = "source_row_number"
    sortDirection: Literal["asc", "desc"] = "asc"


class PositionPageState(BaseModel):
    activeSheet: str
    sheets: dict[str, PositionPageSheetState]
    savedSnapshots: dict[str, PositionPageSavedSnapshot] = Field(default_factory=dict)


class PolicyQueryRequest(BaseModel):
    query: str
    session_id: UUID | None = None
    year: int = 2026
    exam_type: str = "national"
    doc_group: str | None = None
    doc_type: str | None = None
    top_k: int = Field(default=6, ge=1, le=20)
    use_rerank: bool = True
    mode: Literal["policy_rag", "position_recommendation", "autonomous_agent"] | None = None
    intent_hint: str | None = None
    position_profile: PositionRecommendationProfile | None = None
    enable_evaluation: bool = False
    snapshot: dict[str, Any] | None = None
    position_analysis_task_id: UUID | None = None


class ChatRequestBase(BaseModel):
    query: str
    year: int = 2026
    exam_type: str = "national"
    doc_group: str | None = None
    doc_type: str | None = None
    top_k: int = Field(default=6, ge=1, le=20)
    use_rerank: bool = True
    mode: Literal["policy_rag", "position_recommendation", "autonomous_agent"] | None = None
    intent_hint: str | None = None
    position_profile: PositionRecommendationProfile | None = None
    snapshot: dict[str, Any] | None = None
    position_analysis_task_id: UUID | None = None
    enable_evaluation: bool = False


class ChatSessionCreateRequest(BaseModel):
    title: str | None = None


class ChatSessionResponse(BaseModel):
    id: UUID
    title: str
    last_intent: str | None = None
    active_topic: str | None = None
    mentioned_docs: list[str] = Field(default_factory=list)
    summary: str | None = None
    summary_updated_at: datetime | None = None
    created_at: datetime | None = None


class ChatSessionListResponse(BaseModel):
    data: list[ChatSessionResponse]
    count: int


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    intent: str | None = None
    historical_reference: bool = False
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_trace: list[dict[str, Any]] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ChatMessageListResponse(BaseModel):
    data: list[ChatMessageResponse]
    count: int


class ChatAttachmentResponse(BaseModel):
    id: UUID
    session_id: UUID
    file_name: str
    original_name: str
    attachment_type: str
    mime_type: str
    file_path: str
    size_bytes: int
    summary: str | None = None
    extracted_text: str | None = None
    extraction_status: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ChatAttachmentListResponse(BaseModel):
    data: list[ChatAttachmentResponse]
    count: int


class PolicyQueryResponse(BaseModel):
    answer: str
    intent: str
    need_rag: bool
    decision_branch: str | None = None
    citations: list[dict[str, Any]]
    retrieval_trace: list[dict[str, Any]]
    rewritten_queries: list[str]
    metadata_filter: str | None = None
    rerank_results: list[dict[str, Any]]
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    risk_review: dict[str, Any] = Field(default_factory=dict)
    report: str | None = None
    need_more_info: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    recommendation_task_id: str | None = None
    historical_reference: bool = False
    session: ChatSessionResponse | None = None
    user_message: ChatMessageResponse | None = None
    assistant_message: ChatMessageResponse | None = None
    evaluation_run_id: UUID | None = None


class ChunkDebugRecord(BaseModel):
    chunk_id: str
    source_file: str
    doc_group: str
    doc_type: str
    chunk_type: str
    section: str
    question: str
    page_start: int
    page_end: int
    char_count: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkDebugListResponse(BaseModel):
    data: list[ChunkDebugRecord]
    count: int


class ChunkDebugStatsResponse(BaseModel):
    source_file: str | None = None
    doc_group: str | None = None
    doc_type: str | None = None
    total_chunks: int
    chunk_type_count: dict[str, int]
    avg_char_count: float
    min_char_count: int
    max_char_count: int
    missing_question_count: int
    missing_section_count: int
    missing_page_count: int
    fallback_count: int = 0
    fallback_ratio: float


@router.get("/health", response_model=Message)
def health_check() -> Message:
    return Message(message="GwyPilot MVP skeleton is ready")


@router.post("/import/policy-pdfs", response_model=PolicyImportResponse)
def import_policy_pdfs(
    payload: PolicyImportRequest,
    session: SessionDep,
) -> PolicyImportResponse:
    service = PolicyIngestionService(
        session=session,
        owner_user_id=payload.owner_user_id,
        collection_name=payload.collection_name,
    )
    path = Path(payload.path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path not found: {payload.path}",
        )

    try:
        if path.is_dir():
            result = service.ingest_policy_directory(
                str(path),
                owner_user_id=payload.owner_user_id,
                collection_name=payload.collection_name,
            )
        else:
            result = service.ingest_policy_pdf(
                str(path),
                owner_user_id=payload.owner_user_id,
                collection_name=payload.collection_name,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return PolicyImportResponse(
        success=bool(result.get("success", True)),
        file_count=int(result.get("file_count", 0)),
        chunk_count=int(result.get("chunk_count", 0)),
        failed_files=list(result.get("failed_files", [])),
        chunk_stats=(
            dict(result.get("chunk_stats") or {}) if result.get("chunk_stats") else None
        ),
        warnings=list(result.get("warnings", [])),
        debug_artifacts=dict(result.get("debug_artifacts") or {}),
        layout_stats=dict(result.get("layout_stats") or {})
        if result.get("layout_stats")
        else None,
    )


@router.get("/debug/chunks", response_model=ChunkDebugListResponse)
def list_chunk_debugs(
    source_file: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> ChunkDebugListResponse:
    service = ChunkDebugService()
    records = service.list_chunks(
        source_file=source_file,
        limit=limit,
        offset=offset,
    )
    return ChunkDebugListResponse(
        data=[ChunkDebugRecord.model_validate(record) for record in records],
        count=len(records),
    )


@router.get("/debug/chunks/{chunk_id}", response_model=ChunkDebugRecord)
def get_chunk_debug(chunk_id: str) -> ChunkDebugRecord:
    service = ChunkDebugService()
    record = service.get_chunk(chunk_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chunk not found: {chunk_id}",
        )
    return ChunkDebugRecord.model_validate(record)


@router.get("/debug/chunk-stats", response_model=ChunkDebugStatsResponse)
def get_chunk_debug_stats(
    source_file: str | None = None,
) -> ChunkDebugStatsResponse:
    service = ChunkDebugService()
    stats = service.get_chunk_stats(source_file=source_file)
    return ChunkDebugStatsResponse.model_validate(stats)


@router.get("/positions", response_model=PositionListResponse)
def list_positions(
    session: SessionDep,
    current_user: CurrentUser,
    year: int = 2026,
    major: str | None = None,
    education: str | None = None,
    degree: str | None = None,
    political_status: str | None = None,
    region: str | None = None,
    department: str | None = None,
    job_title: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PositionListResponse:
    _ = current_user
    logger.info(
        "Gwy positions list request | user_id=%s year=%s major=%s education=%s degree=%s political_status=%s region=%s department=%s job_title=%s page=%s page_size=%s",
        current_user.id,
        year,
        major,
        education,
        degree,
        political_status,
        region,
        department,
        job_title,
        page,
        page_size,
    )
    service = PositionCatalogService(session)
    result = service.list_positions(
        PositionListFilters(
            year=year,
            major=major,
            education=education,
            degree=degree,
            political_status=political_status,
            region=region,
            department=department,
            job_title=job_title,
            page=page,
            page_size=page_size,
        )
    )
    return PositionListResponse.model_validate(result)


@router.get("/positions/grid", response_model=PositionListResponse)
def list_positions_grid(
    session: SessionDep,
    current_user: CurrentUser,
    year: int = 2026,
    major: str | None = None,
    education: str | None = None,
    degree: str | None = None,
    political_status: str | None = None,
    region: str | None = None,
    department: str | None = None,
    job_title: str | None = None,
) -> PositionListResponse:
    _ = current_user
    logger.info(
        "Gwy positions grid request | user_id=%s year=%s major=%s education=%s degree=%s political_status=%s region=%s department=%s job_title=%s",
        current_user.id,
        year,
        major,
        education,
        degree,
        political_status,
        region,
        department,
        job_title,
    )
    service = PositionCatalogService(session)
    result = service.list_positions_grid(
        PositionListFilters(
            year=year,
            major=major,
            education=education,
            degree=degree,
            political_status=political_status,
            region=region,
            department=department,
            job_title=job_title,
            page=1,
            page_size=0,
        )
    )
    return PositionListResponse.model_validate(result)


@router.post("/positions/analyze", response_model=PositionAnalyzeResponse)
def analyze_positions(
    payload: PositionAnalyzeRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionAnalyzeResponse:
    logger.info(
        "Gwy positions analyze request | user_id=%s position_count=%s top_k=%s",
        current_user.id,
        len(payload.position_ids),
        payload.top_k,
    )
    service = PositionCatalogService(session)
    result = service.analyze_positions(
        position_ids=list(payload.position_ids),
        query=payload.query,
        profile=(
            payload.position_profile.model_dump(exclude_none=True)
            if payload.position_profile is not None
            else None
        ),
        top_k=payload.top_k,
    )
    response = PositionAnalyzeResponse.model_validate(result)
    if payload.enable_evaluation:
        evaluation = record_online_evaluation(
            session=session,
            user_id=current_user.id,
            source_type="position",
            source_id=None,
            query=payload.query,
            output=result,
            profile=(
                payload.position_profile.model_dump(exclude_none=True)
                if payload.position_profile is not None
                else {}
            ),
        )
        response.evaluation_run_id = UUID(str(evaluation["id"]))
    return response


@router.get("/positions/page-state", response_model=PositionPageState)
def get_position_page_state(
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionPageState:
    logger.info(
        "Gwy position page state request | user_id=%s",
        current_user.id,
    )
    service = PositionCatalogService(session)
    payload = service.get_page_state(current_user.id)
    if not payload:
        return PositionPageState(
            activeSheet="涓ぎ鍏氱兢鏈哄叧",
            sheets={
                "涓ぎ鍏氱兢鏈哄叧": PositionPageSheetState(),
                "涓ぎ鍥藉琛屾斂鏈哄叧锛堟湰绾э級": PositionPageSheetState(),
                "涓ぎ鍥藉琛屾斂鏈哄叧鐪佺骇浠ヤ笅鐩村睘鏈烘瀯": PositionPageSheetState(),
                "涓ぎ鍥藉琛屾斂鏈哄叧鍙傜収鍏姟鍛樻硶绠＄悊浜嬩笟鍗曚綅": PositionPageSheetState(),
            },
            savedSnapshots={},
        )
    return PositionPageState.model_validate(payload)


@router.post("/positions/page-state", response_model=PositionPageState)
def save_position_page_state(
    payload: PositionPageState,
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionPageState:
    logger.info(
        "Gwy position page state save request | user_id=%s active_sheet=%s sheets=%s",
        current_user.id,
        payload.activeSheet,
        len(payload.sheets),
    )
    service = PositionCatalogService(session)
    service.save_page_state(current_user.id, payload.model_dump())
    return payload


@router.delete("/positions/page-state")
def clear_position_page_state(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, bool]:
    logger.info(
        "Gwy position page state clear request | user_id=%s",
        current_user.id,
    )
    service = PositionCatalogService(session)
    deleted = service.clear_page_state(current_user.id)
    return {"success": deleted}


@router.post("/policy/search", response_model=PolicySearchResponse)
def search_policy(
    payload: PolicySearchRequest,
) -> PolicySearchResponse:
    filter_expr = _build_filter_expr(
        year=payload.year,
        exam_type=payload.exam_type,
        doc_group=payload.doc_group,
    )
    embedding_service = EmbeddingService()
    store = MilvusPolicyStore()
    rerank_service = RerankService()

    query_vector = embedding_service.embed_text(payload.query)
    results = store.search(
        query_vector=query_vector,
        filter_expr=filter_expr,
        top_k=payload.top_k,
    )
    if payload.use_rerank:
        results = rerank_service.rerank(
            query=payload.query,
            documents=results,
            top_n=payload.top_k,
        )

    return PolicySearchResponse(
        results=[
            PolicySearchResult(
                content=str(item.get("content", "")),
                score=float(item.get("score", 0.0)),
                rerank_score=(
                    float(item["rerank_score"])
                    if item.get("rerank_score") is not None
                    else None
                ),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in results
        ]
    )


@router.post("/policy/query", response_model=PolicyQueryResponse)
def query_policy(
    payload: PolicyQueryRequest,
    session: SessionDep,
) -> PolicyQueryResponse:
    service = PolicyRagService(session=session)
    result = service.query_policy(
        query=payload.query,
        session_id=payload.session_id,
        year=payload.year,
        exam_type=payload.exam_type,
        doc_group=payload.doc_group,
        doc_type=payload.doc_type,
        top_k=payload.top_k,
        use_rerank=payload.use_rerank,
        mode=payload.mode,
        intent_hint=payload.intent_hint,
        position_profile=(
            payload.position_profile.model_dump(exclude_none=True)
            if payload.position_profile is not None
            else None
        ),
    )
    return PolicyQueryResponse.model_validate(result)


@router.get("/chat/sessions", response_model=ChatSessionListResponse)
def list_chat_sessions(
    session: SessionDep,
    current_user: CurrentUser,
) -> ChatSessionListResponse:
    service = ChatSessionService(session)
    sessions = service.list_sessions(current_user.id)
    return ChatSessionListResponse(
        data=[_serialize_chat_session(item) for item in sessions],
        count=len(sessions),
    )


@router.post("/chat/sessions", response_model=ChatSessionResponse)
def create_chat_session(
    payload: ChatSessionCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> ChatSessionResponse:
    service = ChatSessionService(session)
    created = service.create_session(current_user.id, title=payload.title)
    return _serialize_chat_session(created)


@router.delete("/chat/sessions/{session_id}", response_model=Message)
def delete_chat_session(
    session_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    service = ChatSessionService(session)
    try:
        service.delete_session(session_id, current_user.id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found.",
        ) from exc
    return Message(message="Chat session deleted")


@router.get("/profile/me", response_model=UserProfileResponse)
def get_my_profile(
    session: SessionDep,
    current_user: CurrentUser,
) -> UserProfileResponse:
    profile = _get_or_create_user_profile(session, current_user.id)
    return _serialize_user_profile(profile)


@router.put("/profile/me", response_model=UserProfileResponse)
def update_my_profile(
    payload: UserProfileUpdateRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> UserProfileResponse:
    profile = _get_or_create_user_profile(session, current_user.id)

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field_name, value)

    session.add(profile)
    session.commit()
    session.refresh(profile)
    return _serialize_user_profile(profile)


@router.post("/profile/me/feishu/test", response_model=FeishuWebhookTestResponse)
def test_my_feishu_webhook(
    payload: FeishuWebhookTestRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> FeishuWebhookTestResponse:
    webhook_url = (payload.webhook_url or "").strip()
    if not webhook_url:
        profile = _get_or_create_user_profile(session, current_user.id)
        webhook_url = str(profile.feishu_webhook_url or "").strip()
    if not webhook_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please set a Feishu webhook URL first.",
        )

    agent = FeishuPushAgent()
    result = agent.run(
        report_kind="analysis",
        title="GwyPilot 飞书连接测试",
        report_text=(
            "这是一条飞书连接测试消息。\n"
            "如果你能在群里看到这条消息，说明 webhook 已经可用。"
        ),
        task_id=None,
        webhook_url=webhook_url,
    )
    status_text = str(result.get("status") or "unknown")
    if status_text != "sent":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(result.get("error_message") or "Feishu webhook test failed."),
        )
    return FeishuWebhookTestResponse(
        status=status_text,
        detail="Feishu webhook test succeeded.",
        response_json=dict(result.get("response_json") or {}),
        trace=list(result.get("trace") or []),
    )


@router.get("/chat/sessions/{session_id}/messages", response_model=ChatMessageListResponse)
def list_chat_messages(
    session_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> ChatMessageListResponse:
    service = ChatSessionService(session)
    messages = service.list_messages(session_id, current_user.id)
    return ChatMessageListResponse(
        data=[_serialize_chat_message(item) for item in messages],
        count=len(messages),
    )


@router.post(
    "/chat/sessions/{session_id}/messages",
    response_model=PolicyQueryResponse,
)
def create_chat_message(
    session_id: UUID,
    payload: ChatRequestBase,
    session: SessionDep,
    current_user: CurrentUser,
) -> PolicyQueryResponse:
    service = PolicyRagService(session=session)
    result = service.answer_chat_message(
        session_id=session_id,
        user_id=current_user.id,
        query=payload.query,
        year=payload.year,
        exam_type=payload.exam_type,
        doc_group=payload.doc_group,
        doc_type=payload.doc_type,
        top_k=payload.top_k,
        use_rerank=payload.use_rerank,
        mode=payload.mode,
        intent_hint=payload.intent_hint,
        position_profile=(
            payload.position_profile.model_dump(exclude_none=True)
            if payload.position_profile is not None
            else None
        ),
    )
    response = PolicyQueryResponse.model_validate(result)
    if payload.enable_evaluation:
        evaluation = record_online_evaluation(
            session=session,
            user_id=current_user.id,
            source_type="chat",
            source_id=str(session_id),
            query=payload.query,
            output=result,
            profile=(
                payload.position_profile.model_dump(exclude_none=True)
                if payload.position_profile is not None
                else {}
            ),
        )
        response.evaluation_run_id = UUID(str(evaluation["id"]))
    return response


@router.post("/chat/sessions/{session_id}/messages/stream")
def create_chat_message_stream(
    session_id: UUID,
    payload: ChatRequestBase,
    session: SessionDep,
    current_user: CurrentUser,
) -> StreamingResponse:
    service = PolicyRagService(session=session)

    def event_stream() -> Iterator[str]:
        try:
            current_stage = "init"
            pipeline_started_at = time.perf_counter()
            service.session_service.get_session(session_id, current_user.id)
            user_message = service.session_service.append_message(
                session_id=session_id,
                role="user",
                content=payload.query,
            )
            if payload.mode in {None, "autonomous_agent", "policy_rag"}:
                current_stage = "autonomous_agent"
                yield _sse_stage_event(
                    "autonomous_agent",
                    "running",
                    detail="自主 Agent 正在规划、调用工具并生成回答",
                    elapsed_ms=0,
                )
                agent_started_at = time.perf_counter()
                trace_queue: Queue[dict[str, Any]] = Queue()
                result_box: dict[str, Any] = {}
                error_box: dict[str, BaseException] = {}
                sent_trace_ids: set[str] = set()
                position_profile = (
                    payload.position_profile.model_dump(exclude_none=True)
                    if payload.position_profile is not None
                    else None
                )

                def on_agent_event(event: dict[str, Any]) -> None:
                    trace_queue.put(event)

                def run_autonomous_agent() -> None:
                    try:
                        with Session(engine) as worker_session:
                            autonomous_service = AutonomousChatAgentService(
                                session=worker_session,
                            )
                            result_box["result"] = autonomous_service.run(
                                query=payload.query,
                                user_id=current_user.id,
                                session_id=session_id,
                                year=payload.year,
                                exam_type=payload.exam_type,
                                top_k=payload.top_k,
                                position_profile=position_profile,
                                snapshot=payload.snapshot,
                                position_analysis_task_id=payload.position_analysis_task_id,
                                on_event=on_agent_event,
                            )
                    except BaseException as exc:  # pragma: no cover - stream guard
                        error_box["error"] = exc
                    finally:
                        trace_queue.put({"__done__": True})

                worker = Thread(
                    target=run_autonomous_agent,
                    name=f"gwy-autonomous-agent-{session_id}",
                    daemon=True,
                )
                worker.start()
                while True:
                    try:
                        item = trace_queue.get(timeout=0.25)
                    except Empty:
                        if worker.is_alive():
                            continue
                        break
                    if item.get("__done__"):
                        break
                    trace_id = str(item.get("id") or "")
                    if trace_id and trace_id in sent_trace_ids:
                        continue
                    if trace_id:
                        sent_trace_ids.add(trace_id)
                    yield _sse_event("trace", {"trace": item})
                worker.join(timeout=1)
                if error_box:
                    error = error_box["error"]
                    logger.error(
                        "Autonomous agent stream failed",
                        exc_info=(type(error), error, error.__traceback__),
                    )
                    yield _sse_stage_event(
                        "autonomous_agent",
                        "error",
                        detail="自主 Agent 执行失败",
                        elapsed_ms=_elapsed_ms(agent_started_at),
                    )
                    yield _sse_event(
                        "error",
                        {
                            "stage": "autonomous_agent",
                            "detail": str(error),
                        },
                    )
                    return
                result = dict(result_box.get("result") or {})
                yield _sse_stage_event(
                    "autonomous_agent",
                    "done",
                    detail="自主 Agent 已完成工具调用与回答整理",
                    elapsed_ms=_elapsed_ms(agent_started_at),
                )
                for item in list(result.get("retrieval_trace") or []):
                    trace_id = str(item.get("id") or "")
                    if trace_id and trace_id in sent_trace_ids:
                        continue
                    if trace_id:
                        sent_trace_ids.add(trace_id)
                    yield _sse_event("trace", {"trace": item})
                if str(result.get("report") or "").strip():
                    yield _sse_event("report", {"report": str(result.get("report") or "")})
                answer = service._normalize_answer_text(str(result.get("answer") or ""))
                citations = list(result.get("citations") or [])
                if citations:
                    yield _sse_event("sources", {"citations": citations})
                if answer.strip():
                    yield from (
                        _sse_event("delta", {"delta": chunk})
                        for chunk in _batch_stream_chunks(iter([answer]))
                    )
                finalize_started_at = time.perf_counter()
                yield _sse_stage_event(
                    "finalize",
                    "running",
                    detail="正在保存自主 Agent 对话与报告",
                    elapsed_ms=0,
                )
                payload_data = service.finalize_chat_turn(
                    session_id=session_id,
                    user_id=current_user.id,
                    query=payload.query,
                    user_message=service._serialize_message(user_message),
                    result=result,
                )
                if payload.enable_evaluation:
                    evaluation = record_online_evaluation(
                        session=session,
                        user_id=current_user.id,
                        source_type="chat",
                        source_id=str(session_id),
                        query=payload.query,
                        output=result,
                    )
                    payload_data["evaluation_run_id"] = str(evaluation["id"])
                yield _sse_stage_event(
                    "finalize",
                    "done",
                    detail="会话已保存",
                    elapsed_ms=_elapsed_ms(finalize_started_at),
                    total_elapsed_ms=_elapsed_ms(pipeline_started_at),
                )
                yield _sse_event("done", payload_data)
                return
            state = {
                "query": payload.query,
                "session_id": str(session_id),
                "user_id": str(current_user.id),
                "year": payload.year,
                "exam_type": payload.exam_type,
                "doc_group": payload.doc_group,
                "doc_type": payload.doc_type,
                "top_k": payload.top_k,
                "use_rerank": payload.use_rerank,
                "mode": payload.mode,
                "intent_hint": payload.intent_hint,
                "position_profile": (
                    payload.position_profile.model_dump(exclude_none=True)
                    if payload.position_profile is not None
                    else None
                ),
                "retrieval_trace": [],
            }
            state["memory_context"] = service.session_service.get_memory_context(
                session_id=session_id,
                user_id=current_user.id,
            )
            state["session_attachments"] = service._load_session_attachments(  # noqa: SLF001
                session_id=session_id,
                user_id=current_user.id,
            )

            yield _sse_stage_event(
                "route_intent",
                "running",
                detail="正在判断问题是否需要检索知识库",
                elapsed_ms=0,
            )
            current_stage = "route_intent"
            route_started_at = time.perf_counter()
            state.update(service._node_route_intent(state))
            yield _sse_stage_event(
                "route_intent",
                "done",
                detail="已完成意图识别",
                elapsed_ms=_elapsed_ms(route_started_at),
            )

            answer_parts: list[str] = []
            reasoning_parts: list[str] = []
            citations = list(state.get("citations") or [])

            def stream_model_output(
                stream: Iterator[dict[str, Any] | str],
            ) -> Iterator[str]:
                content_buffer = ""

                def flush_content() -> Iterator[str]:
                    nonlocal content_buffer
                    if not content_buffer:
                        return
                    yield content_buffer
                    content_buffer = ""

                for chunk in stream:
                    if isinstance(chunk, dict):
                        chunk_type = str(chunk.get("type") or "content")
                        text = str(chunk.get("text") or "")
                    else:
                        chunk_type = "content"
                        text = str(chunk)
                    if not text:
                        continue
                    if chunk_type == "reasoning":
                        yield from flush_content()
                        reasoning_parts.append(text)
                        yield _sse_event("reasoning", {"delta": text})
                        continue
                    content_buffer += text
                    if len(content_buffer) >= 72 or (
                        len(content_buffer) >= 24
                        and content_buffer[-1] in _STREAM_FLUSH_PUNCTUATION
                    ):
                        answer_parts.append(content_buffer)
                        yield _sse_event("delta", {"delta": content_buffer})
                        content_buffer = ""
                yield from flush_content()
            if str(state.get("intent") or "") == "position_recommendation":
                position_started_at = time.perf_counter()
                yield _sse_stage_event(
                    "position_recommendation",
                    "running",
                    detail="正在基于岗位表筛选适合的岗位",
                    elapsed_ms=0,
                )
                current_stage = "position_recommendation"
                state.update(service._node_position_recommendation(state))
                yield _sse_stage_event(
                    "position_recommendation",
                    "done",
                    detail="已完成岗位筛选与推荐",
                    elapsed_ms=_elapsed_ms(position_started_at),
                )
                answer = service._normalize_answer_text(
                    str(state.get("answer") or "")
                )
                if answer.strip():
                    answer_parts.append(answer)
                    yield _sse_event("delta", {"delta": answer})
                yield _sse_event(
                    "meta",
                    {
                        "session_id": str(session_id),
                        "intent": state.get("intent"),
                        "need_rag": bool(state.get("need_rag", True)),
                        "recommendation_count": len(
                            state.get("recommendations") or []
                        ),
                    },
                )
            elif not bool(state.get("need_rag", True)):
                yield _sse_event(
                    "meta",
                    {
                        "session_id": str(session_id),
                        "intent": state.get("intent"),
                        "need_rag": bool(state.get("need_rag", True)),
                        "citation_count": len(citations),
                    },
                )
                prompt = service._build_direct_answer_prompt(state)
                yield _sse_stage_event(
                    "direct_answer",
                    "running",
                    detail="正在生成直接回答",
                    elapsed_ms=0,
                )
                answer_started_at = time.perf_counter()
                try:
                    stream = service.chat_service.stream_chat_completion(
                        [
                            {"role": "system", "content": DIRECT_ANSWER_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                    )
                    yield from stream_model_output(stream)
                except Exception:
                    fallback_answer = service._generate_direct_answer(prompt, state)
                    answer_parts = [fallback_answer]
                    yield _sse_event("delta", {"delta": fallback_answer})
                yield _sse_stage_event(
                    "direct_answer",
                    "done",
                    detail="已完成直接回答生成",
                    elapsed_ms=_elapsed_ms(answer_started_at),
                )
            else:
                rewrite_started_at = time.perf_counter()
                yield _sse_stage_event(
                    "rewrite_queries",
                    "running",
                    detail="正在改写问题，准备检索",
                    elapsed_ms=0,
                )
                current_stage = "rewrite_queries"
                state.update(service._node_rewrite_queries(state))
                yield _sse_stage_event(
                    "rewrite_queries",
                    "done",
                    detail="已完成问题改写",
                    elapsed_ms=_elapsed_ms(rewrite_started_at),
                )

                retrieve_started_at = time.perf_counter()
                yield _sse_stage_event(
                    "retrieve",
                    "running",
                    detail="正在检索相关政策材料",
                    elapsed_ms=0,
                )
                current_stage = "retrieve"
                state.update(service._node_retrieve(state))
                yield _sse_stage_event(
                    "retrieve",
                    "done",
                    detail="已完成知识检索",
                    elapsed_ms=_elapsed_ms(retrieve_started_at),
                )

                rerank_started_at = time.perf_counter()
                yield _sse_stage_event(
                    "fuse_and_rerank",
                    "running",
                    detail="正在融合结果并进行重排",
                    elapsed_ms=0,
                )
                current_stage = "fuse_and_rerank"
                state.update(service._node_fuse_and_rerank(state))
                yield _sse_stage_event(
                    "fuse_and_rerank",
                    "done",
                    detail="已完成融合与重排",
                    elapsed_ms=_elapsed_ms(rerank_started_at),
                )

                react_started_at = time.perf_counter()
                yield _sse_stage_event(
                    "react_evidence_review",
                    "running",
                    detail="正在复核证据是否足够支撑回答",
                    elapsed_ms=0,
                )
                current_stage = "react_evidence_review"
                state.update(service._node_react_evidence_review(state))
                yield _sse_stage_event(
                    "react_evidence_review",
                    "done",
                    detail="已完成证据复核",
                    elapsed_ms=_elapsed_ms(react_started_at),
                )

                citations = list(state.get("citations") or [])
                yield _sse_event(
                    "meta",
                    {
                        "session_id": str(session_id),
                        "intent": state.get("intent"),
                        "need_rag": bool(state.get("need_rag", True)),
                        "citation_count": len(citations),
                    },
                )
                prompt = service._build_answer_prompt(state, citations)
                yield _sse_stage_event(
                    "answer",
                    "running",
                    detail="正在生成基于证据的回答",
                    elapsed_ms=0,
                )
                answer_started_at = time.perf_counter()
                try:
                    current_stage = "answer"
                    stream = service.chat_service.stream_chat_completion(
                        [
                            {"role": "system", "content": POLICY_RAG_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                    )
                    yield from stream_model_output(stream)
                except Exception:
                    fallback_answer = service._generate_answer(prompt, citations)
                    answer_parts = [fallback_answer]
                    yield _sse_event("delta", {"delta": fallback_answer})
                yield _sse_stage_event(
                    "answer",
                    "done",
                    detail="已完成回答生成",
                    elapsed_ms=_elapsed_ms(answer_started_at),
                )

            answer = service._normalize_answer_text("".join(answer_parts))
            if not answer.strip():
                logger.warning(
                    "Empty streamed answer; falling back to non-streamed generation. session_id=%s user_id=%s stage=%s",
                    session_id,
                    current_user.id,
                    current_stage,
                )
                if bool(state.get("need_rag", True)):
                    fallback_prompt = service._build_answer_prompt(state, citations)
                    answer = service._generate_answer(fallback_prompt, citations)
                else:
                    fallback_prompt = service._build_direct_answer_prompt(state)
                    answer = service._generate_direct_answer(fallback_prompt, state)
            result = service._build_result_payload(state, answer)
            finalize_started_at = time.perf_counter()
            yield _sse_stage_event(
                "finalize",
                "running",
                detail="正在保存会话与消息",
                elapsed_ms=0,
            )
            current_stage = "finalize"
            payload_data = service.finalize_chat_turn(
                session_id=session_id,
                user_id=current_user.id,
                query=payload.query,
                user_message=service._serialize_message(user_message),
                result=result,
            )
            if payload.enable_evaluation:
                evaluation = record_online_evaluation(
                    session=session,
                    user_id=current_user.id,
                    source_type="chat",
                    source_id=str(session_id),
                    query=payload.query,
                    output=result,
                )
                payload_data["evaluation_run_id"] = str(evaluation["id"])
            reasoning_content = "".join(reasoning_parts).strip()
            if reasoning_content:
                assistant_message = payload_data.get("assistant_message")
                if isinstance(assistant_message, dict):
                    metadata_json = assistant_message.get("metadata_json")
                    if not isinstance(metadata_json, dict):
                        metadata_json = {}
                        assistant_message["metadata_json"] = metadata_json
                    metadata_json["reasoning_content"] = reasoning_content
            yield _sse_stage_event(
                "finalize",
                "done",
                detail="会话已保存",
                elapsed_ms=_elapsed_ms(finalize_started_at),
                total_elapsed_ms=_elapsed_ms(pipeline_started_at),
            )
            yield _sse_event("done", payload_data)
        except Exception as exc:
            logger.exception(
                "Gwy chat stream failed at stage=%s session_id=%s user_id=%s",
                current_stage,
                session_id,
                current_user.id,
            )
            yield _sse_event(
                "error",
                {
                    "detail": str(exc),
                    "stage": current_stage,
                    "error_type": exc.__class__.__name__,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/audio/speech")
def create_audio_speech(
    payload: TextToSpeechRequest,
    current_user: CurrentUser,
) -> Response:
    _ = current_user
    normalized_text = _normalize_speech_text(payload.text)
    if not normalized_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Speech text cannot be empty.",
        )

    client = SiliconFlowClient()
    try:
        audio_bytes = client.speech(
            f"[S1]{normalized_text}",
            voice=payload.voice,
            response_format="mp3",
            stream=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Audio synthesis failed: {exc}",
        ) from exc

    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.get("/chat/sessions/{session_id}/attachments", response_model=ChatAttachmentListResponse)
def list_chat_attachments(
    session_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> ChatAttachmentListResponse:
    service = ChatSessionService(session)
    attachments = service.list_attachments(session_id, current_user.id)
    return ChatAttachmentListResponse(
        data=[_serialize_chat_attachment(item) for item in attachments],
        count=len(attachments),
    )


@router.post(
    "/chat/sessions/{session_id}/attachments",
    response_model=ChatAttachmentListResponse,
)
async def upload_chat_attachments(
    session_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
    files: list[UploadFile] = File(...),
) -> ChatAttachmentListResponse:
    chat_service = ChatSessionService(session)
    try:
        chat_service.get_session(session_id, current_user.id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found.",
        ) from exc

    repo_root = Path(__file__).resolve().parents[4]
    upload_root = repo_root / "data" / "processed" / "chat_uploads" / str(session_id)
    upload_root.mkdir(parents=True, exist_ok=True)

    multimodal_service = MultimodalSummaryService()
    attachments: list[GwyChatAttachment] = []

    for upload in files:
        original_name = upload.filename or "upload"
        suffix = Path(original_name).suffix.lower()
        safe_name = _safe_filename(original_name)
        stored_name = f"{uuid4().hex}_{safe_name}"
        stored_path = upload_root / stored_name
        file_bytes = await upload.read()
        stored_path.write_bytes(file_bytes)

        mime_type = upload.content_type or _mime_type_for_suffix(suffix)
        attachment_type = _attachment_type_for_file(suffix=suffix, mime_type=mime_type)
        summary: str | None = None
        extracted_text: str | None = None
        extraction_status = "uploaded"

        if attachment_type == "image":
            multimodal_result = multimodal_service.summarize_image(
                image_path=str(stored_path),
                nearby_text="",
                source_file=original_name,
            )
            summary = str(multimodal_result.get("summary") or "")
            extracted_text = str(multimodal_result.get("ocr_text") or "")
            extraction_status = str(multimodal_result.get("extraction_status") or "success")
        elif attachment_type == "pdf":
            try:
                pages = load_pdf_pages(str(stored_path))
                extracted_text = "\n\n".join(
                    str(page.get("text", "")).strip() for page in pages if str(page.get("text", "")).strip()
                )
                summary = _summarize_text(extracted_text)
                extraction_status = "text_extracted"
            except Exception:
                extracted_text = ""
                summary = "已上传 PDF 附件，当前仅保存文件，暂未完成文本提取。"
                extraction_status = "pending_text_extraction"
        elif attachment_type == "text":
            try:
                extracted_text = file_bytes.decode("utf-8", errors="replace").strip()
                summary = _summarize_text(extracted_text)
                extraction_status = "text_extracted"
            except Exception:
                extracted_text = ""
                summary = "已上传文本附件，但暂未完成文本提取。"
                extraction_status = "pending_text_extraction"
        else:
            summary = "已上传附件，等待后续处理。"
            extraction_status = "unsupported_attachment_type"

        attachment = chat_service.add_attachment(
            session_id=session_id,
            file_name=stored_name,
            original_name=original_name,
            attachment_type=attachment_type,
            mime_type=mime_type,
            file_path=str(stored_path),
            size_bytes=len(file_bytes),
            summary=summary,
            extracted_text=extracted_text,
            extraction_status=extraction_status,
            metadata_json={
                "upload_root": str(upload_root),
                "content_type": upload.content_type,
            },
        )

        if attachment_type == "pdf" and not str(attachment.extracted_text or "").strip():
            fallback_summary, fallback_text, fallback_status = _extract_pdf_attachment_content(
                stored_path=stored_path,
                original_name=original_name,
                multimodal_service=multimodal_service,
            )
            attachment.summary = fallback_summary
            attachment.extracted_text = fallback_text
            attachment.extraction_status = fallback_status
            session.add(attachment)
            session.commit()
            session.refresh(attachment)

        attachments.append(attachment)

    return ChatAttachmentListResponse(
        data=[_serialize_chat_attachment(item) for item in attachments],
        count=len(attachments),
    )


@router.delete(
    "/chat/sessions/{session_id}/attachments/{attachment_id}",
    response_model=Message,
)
def delete_chat_attachment(
    session_id: UUID,
    attachment_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    service = ChatSessionService(session)
    try:
        service.delete_attachment(session_id, current_user.id, attachment_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat attachment not found.",
        ) from exc
    return Message(message="Chat attachment deleted")


def _extract_pdf_attachment_content(
    *,
    stored_path: Path,
    original_name: str,
    multimodal_service: MultimodalSummaryService,
) -> tuple[str, str, str]:
    try:
        pages = load_pdf_pages(str(stored_path))
    except Exception:
        pages = []

    if pages:
        extracted_text = "\n\n".join(
            str(page.get("text", "")).strip()
            for page in pages
            if str(page.get("text", "")).strip()
        ).strip()
        if extracted_text:
            return _summarize_text(extracted_text), extracted_text, "text_extracted"

    multimodal_summary = _summarize_pdf_pages_with_multimodal(
        stored_path=stored_path,
        original_name=original_name,
        multimodal_service=multimodal_service,
    )
    if multimodal_summary:
        return multimodal_summary, multimodal_summary, "multimodal_summary"

    return (
        "已上传 PDF 附件，当前仅保存文件，暂未完成文本提取。",
        "",
        "pending_text_extraction",
    )


def _summarize_pdf_pages_with_multimodal(
    *,
    stored_path: Path,
    original_name: str,
    multimodal_service: MultimodalSummaryService,
    max_pages: int = 3,
) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:
        return ""

    summaries: list[str] = []
    with tempfile.TemporaryDirectory(prefix="gwy_pdf_preview_") as tmp_dir:
        temp_root = Path(tmp_dir)
        try:
            document = fitz.open(str(stored_path))
        except Exception:
            return ""

        try:
            for page_index, page in enumerate(document, start=1):
                if page_index > max_pages:
                    break
                image_path = temp_root / f"page_{page_index}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                pixmap.save(str(image_path))
                result = multimodal_service.summarize_image(
                    image_path=str(image_path),
                    nearby_text="",
                    source_file=original_name,
                    page=page_index,
                )
                page_summary = str(
                    result.get("summary") or result.get("ocr_text") or ""
                ).strip()
                if page_summary:
                    summaries.append(f"第{page_index}页：{page_summary}")
        finally:
            document.close()

    return _summarize_text("\n".join(summaries), limit=1200)


def _serialize_chat_session(chat_session: GwyChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=chat_session.id,
        title=chat_session.title,
        last_intent=chat_session.last_intent,
        active_topic=chat_session.active_topic,
        mentioned_docs=list(chat_session.mentioned_docs or []),
        summary=chat_session.summary,
        summary_updated_at=chat_session.summary_updated_at,
        created_at=chat_session.created_at,
    )


def _serialize_chat_message(message: GwyChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        intent=message.intent,
        historical_reference=message.historical_reference,
        citations=list(message.citations or []),
        retrieval_trace=list(message.retrieval_trace or []),
        metadata_json=dict(message.metadata_json or {}),
        created_at=message.created_at,
    )


def _serialize_chat_attachment(attachment: GwyChatAttachment) -> ChatAttachmentResponse:
    return ChatAttachmentResponse(
        id=attachment.id,
        session_id=attachment.session_id,
        file_name=attachment.file_name,
        original_name=attachment.original_name,
        attachment_type=attachment.attachment_type,
        mime_type=attachment.mime_type,
        file_path=attachment.file_path,
        size_bytes=attachment.size_bytes,
        summary=attachment.summary,
        extracted_text=attachment.extracted_text,
        extraction_status=attachment.extraction_status,
        metadata_json=dict(attachment.metadata_json or {}),
        created_at=attachment.created_at,
    )


def _serialize_user_profile(profile: GwyUserProfile) -> UserProfileResponse:
    return UserProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        name=profile.name,
        nickname=profile.nickname,
        education=profile.education,
        degree=profile.degree,
        major=profile.major,
        political_status=profile.political_status,
        is_fresh_graduate=profile.is_fresh_graduate,
        grassroots_experience_years=profile.grassroots_experience_years,
        target_regions=list(profile.target_regions or []),
        avoid_conditions=list(profile.avoid_conditions or []),
        desired_departments=list(profile.desired_departments or []),
        desired_positions=list(profile.desired_positions or []),
        excluded_positions=list(profile.excluded_positions or []),
        daily_study_hours=profile.daily_study_hours,
        notes=profile.notes,
        feishu_webhook_url=profile.feishu_webhook_url,
    )


def _get_or_create_user_profile(
    session: Session,
    user_id: UUID,
) -> GwyUserProfile:
    statement = select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
    profile = session.exec(statement).first()
    if profile is not None:
        return profile

    profile = GwyUserProfile(user_id=user_id)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_stage_event(
    step: str,
    status: str,
    *,
    detail: str,
    elapsed_ms: int,
    total_elapsed_ms: int | None = None,
) -> str:
    data: dict[str, Any] = {
        "step": step,
        "label": _PIPELINE_STAGE_LABELS.get(step, step),
        "status": status,
        "detail": detail,
        "elapsed_ms": elapsed_ms,
    }
    if total_elapsed_ms is not None:
        data["total_elapsed_ms"] = total_elapsed_ms
    return _sse_event("stage", data)


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _normalize_speech_text(text: str) -> str:
    cleaned = text.replace("```", " ")
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_>`~]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _batch_stream_chunks(
    chunks: Iterator[str],
    *,
    min_chars: int = 24,
    max_chars: int = 72,
) -> Iterator[str]:
    buffer = ""
    for chunk in chunks:
        if not chunk:
            continue
        cleaned = chunk.replace("*", "")
        if not cleaned:
            continue
        for char in cleaned:
            buffer += char
            if len(buffer) >= max_chars:
                yield buffer
                buffer = ""
                continue
            if len(buffer) >= min_chars and buffer[-1] in _STREAM_FLUSH_PUNCTUATION:
                yield buffer
                buffer = ""
    if buffer:
        yield buffer


def _build_filter_expr(
    *,
    year: int | None,
    exam_type: str | None,
    doc_group: str | None,
) -> str | None:
    parts: list[str] = []
    if year is not None:
        parts.append(f"year == {year}")
    if exam_type:
        parts.append(f'exam_type == "{_escape_expr(exam_type)}"')
    if doc_group:
        parts.append(f'doc_group == "{_escape_expr(doc_group)}"')
    return " and ".join(parts) if parts else None


def _escape_expr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _safe_filename(filename: str) -> str:
    import re

    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return stem or "upload"


def _mime_type_for_suffix(suffix: str) -> str:
    mapping = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")


# ?? Memory endpoints ??????????????????????????????????????????????


class MemoryContextResponse(BaseModel):
    session_summary: str | None = None
    last_intent: str | None = None
    active_topic: str | None = None
    mentioned_docs: list[str] = Field(default_factory=list)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    conversation_memory: dict[str, Any] = Field(default_factory=dict)
    extracted_preferences: dict[str, Any] = Field(default_factory=dict)
    long_term_context: dict[str, Any] = Field(default_factory=dict)
    user_profile: dict[str, Any] = Field(default_factory=dict)
    memory_prompt: str = ""


@router.get("/memory/context", response_model=MemoryContextResponse)
def get_memory_context(
    session_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    chat_svc = ChatSessionService(session=session)
    return chat_svc.get_memory_context(
        session_id=session_id,
        user_id=current_user.id,
    )


class LongTermMemoryResponse(BaseModel):
    total_analyses: int = 0
    total_decisions: int = 0
    liked_departments: list[str] = Field(default_factory=list)
    liked_job_titles: list[str] = Field(default_factory=list)
    last_analysis_at: str | None = None
    user_profile: dict[str, Any] = Field(default_factory=dict)


@router.get("/memory/long-term", response_model=LongTermMemoryResponse)
def get_long_term_memory(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    ltm_service = LongTermMemoryService(session=session)
    return ltm_service.build_cross_session_summary(user_id=current_user.id)


class RecordDecisionRequest(BaseModel):
    position_id: UUID | None = None
    decision_type: str  # like / dislike / view
    decision_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/memory/decision")
def record_decision(
    body: RecordDecisionRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    ltm_service = LongTermMemoryService(session=session)
    decision = ltm_service.record_position_decision(
        user_id=current_user.id,
        position_id=body.position_id,
        decision_type=body.decision_type,
        decision_reason=body.decision_reason,
        metadata=body.metadata,
    )
    return {
        "id": str(decision.id),
        "decision_type": decision.decision_type,
        "created_at": str(decision.created_at) if decision.created_at else None,
    }


# ?? Study Plan endpoints ??????????????????????????????????????????


class GenerateStudyPlanRequest(BaseModel):
    task_id: UUID | None = None
    exam_type: str = "??"
    exam_year: int | None = None
    study_hours_per_day: int = 4
    push_to_feishu: bool = False


class StudyPlanItem(BaseModel):
    id: str
    title: str
    exam_type: str | None = None
    exam_year: int | None = None
    total_weeks: int = 12
    status: str = "draft"
    created_at: str | None = None


class StudyPlanDetailResponse(BaseModel):
    plan: dict[str, Any]
    phases: list[dict[str, Any]] = Field(default_factory=list)
    subjects: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    markdown: str | None = None


class StudyPlanListResponse(BaseModel):
    plans: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/study-plan/generate", response_model=StudyPlanDetailResponse)
def generate_study_plan(
    body: GenerateStudyPlanRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    # Load user profile and recent recommendations
    profile_stmt = select(GwyUserProfile).where(
        GwyUserProfile.user_id == current_user.id
    )
    profile = session.exec(profile_stmt).first()
    user_profile: dict[str, Any] = {}
    if profile is not None:
        user_profile = {
            "name": profile.name,
            "nickname": profile.nickname,
            "education": profile.education,
            "degree": profile.degree,
            "major": profile.major,
            "political_status": profile.political_status,
            "target_regions": profile.target_regions,
            "desired_departments": profile.desired_departments,
            "daily_study_hours": profile.daily_study_hours,
        }

    # Get recommendations from last task
    recommendations: list[dict[str, Any]] = []
    if body.task_id:
        from sqlmodel import select as _sel

        from app.gwy.models import GwyRecommendationItem
        recs = session.exec(
            _sel(GwyRecommendationItem).where(
                GwyRecommendationItem.task_id == body.task_id
            ).limit(20)
        ).all()
        for r in recs:
            recommendations.append({
                "id": str(r.position_id) if r.position_id else "",
                "job_title": r.job_title or "",
                "department_name": r.department_name or "",
                "exam_category": r.exam_category or "",
                "position_desc": r.position_desc or "",
                "major_requirement": r.major_requirement or "",
            })

    svc = StudyPlanService(session=session)
    return svc.generate(
        user_id=current_user.id,
        user_profile=user_profile,
        recommendations=recommendations,
        task_id=body.task_id,
        exam_type=body.exam_type,
        exam_year=body.exam_year,
        study_hours_per_day=body.study_hours_per_day,
        push_to_feishu=body.push_to_feishu,
    )


@router.get("/study-plan/{plan_id}", response_model=StudyPlanDetailResponse)
def get_study_plan(
    plan_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    svc = StudyPlanService(session=session)
    plan = svc.get_plan(plan_id=plan_id, user_id=current_user.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Study plan not found")
    return plan


@router.get("/study-plan/my", response_model=StudyPlanListResponse)
def list_study_plans(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    svc = StudyPlanService(session=session)
    return {"plans": svc.list_plans(user_id=current_user.id)}


@router.delete("/study-plan/{plan_id}")
def delete_study_plan(
    plan_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    svc = StudyPlanService(session=session)
    deleted = svc.delete_plan(plan_id=plan_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Study plan not found")
    return {"deleted": True}



def _attachment_type_for_file(*, suffix: str, mime_type: str) -> str:
    if mime_type.startswith("image/") or suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".gif",
    }:
        return "image"
    if mime_type == "application/pdf" or suffix.lower() == ".pdf":
        return "pdf"
    if mime_type.startswith("text/") or suffix.lower() in {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".json",
        ".log",
        ".xml",
        ".html",
        ".htm",
    }:
        return "text"
    return "other"


def _summarize_text(text: str, limit: int = 800) -> str:
    cleaned = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if not cleaned:
        return "已上传 PDF 附件，未提取到可用文本。"
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3]}..."
