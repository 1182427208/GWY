import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Index
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


class GwyTimestampMixin(SQLModel):
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )


class GwyUserProfile(SQLModel, table=True):
    __tablename__ = "gwy_user_profile"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, unique=True, index=True
    )
    name: str | None = Field(default=None, max_length=255)
    nickname: str | None = Field(default=None, max_length=255)
    education: str | None = Field(default=None, max_length=255)
    degree: str | None = Field(default=None, max_length=255)
    major: str | None = Field(default=None, max_length=255)
    political_status: str | None = Field(default=None, max_length=255)
    is_fresh_graduate: bool = False
    grassroots_experience_years: int | None = None
    target_regions: list[str] = Field(default_factory=list, sa_type=JSON)
    avoid_conditions: list[str] = Field(default_factory=list, sa_type=JSON)
    desired_departments: list[str] = Field(default_factory=list, sa_type=JSON)
    desired_positions: list[str] = Field(default_factory=list, sa_type=JSON)
    excluded_positions: list[str] = Field(default_factory=list, sa_type=JSON)
    daily_study_hours: int | None = None
    notes: str | None = Field(default=None)
    feishu_webhook_url: str | None = Field(default=None, max_length=1024)


class GwyPosition(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_position"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    department_code: str | None = Field(default=None, max_length=32, index=True)
    department_name: str | None = Field(default=None, max_length=255, index=True)
    office_name: str | None = Field(default=None, max_length=255)
    institution_type: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255, index=True)
    position_attribute: str | None = Field(default=None, max_length=255)
    position_distribution: str | None = Field(default=None, max_length=255)
    position_desc: str | None = Field(default=None)
    position_code: str | None = Field(default=None, max_length=64, index=True)
    institution_level: str | None = Field(default=None, max_length=255)
    exam_category: str | None = Field(default=None, max_length=255)
    recruit_count: int | None = None
    major_requirement: str | None = Field(default=None)
    education_requirement: str | None = Field(default=None, max_length=255)
    degree_requirement: str | None = Field(default=None, max_length=255)
    political_status_requirement: str | None = Field(default=None, max_length=255)
    grassroots_years_requirement: str | None = Field(default=None, max_length=255)
    grassroots_project_experience: str | None = Field(default=None, max_length=255)
    professional_test_in_interview: str | None = Field(default=None, max_length=255)
    interview_ratio: str | None = Field(default=None, max_length=32)
    work_location: str | None = Field(default=None, max_length=255)
    household_registration_location: str | None = Field(default=None, max_length=255)
    remarks: str | None = Field(default=None)
    department_website: str | None = Field(default=None, max_length=512)
    contact_phone_1: str | None = Field(default=None, max_length=64)
    contact_phone_2: str | None = Field(default=None, max_length=64)
    contact_phone_3: str | None = Field(default=None, max_length=64)
    source_file: str = Field(max_length=512, index=True)
    source_sheet: str = Field(max_length=255, index=True)
    source_row_number: int
    raw_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyPolicyDocument(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_policy_document"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_file: str = Field(max_length=512, index=True)
    doc_title: str = Field(max_length=255, index=True)
    doc_group: str = Field(max_length=64, index=True)
    doc_type: str = Field(max_length=64, index=True)
    year: int = Field(index=True)
    exam_type: str = Field(max_length=64, index=True)
    province: str = Field(max_length=64, index=True)
    chunk_count: int = 0
    milvus_collection: str = Field(max_length=255, index=True)
    embedding_status: str = Field(default="pending", max_length=32, index=True)


class GwyPdfAsset(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_pdf_asset"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    asset_type: str = Field(max_length=32, index=True)
    source_file: str = Field(max_length=512, index=True)
    page: int = Field(index=True)
    bbox: list[float] = Field(default_factory=list, sa_type=JSON)
    image_path: str | None = Field(default=None, max_length=1024)
    nearby_text: str | None = Field(default=None)
    summary: str | None = Field(default=None)
    ocr_text: str | None = Field(default=None)
    extraction_status: str = Field(default="pending", max_length=64, index=True)
    linked_chunk_ids: list[str] = Field(default_factory=list, sa_type=JSON)


class GwyPdfTable(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_pdf_table"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_file: str = Field(max_length=512, index=True)
    page_start: int = Field(index=True)
    page_end: int = Field(index=True)
    bbox: list[float] = Field(default_factory=list, sa_type=JSON)
    columns: list[str] = Field(default_factory=list, sa_type=JSON)
    markdown_content: str | None = Field(default=None)
    table_image_path: str | None = Field(default=None, max_length=1024)
    extraction_status: str = Field(default="pending", max_length=64, index=True)
    is_cross_page: bool = False
    source_pages: list[int] = Field(default_factory=list, sa_type=JSON)
    linked_chunk_ids: list[str] = Field(default_factory=list, sa_type=JSON)


class GwyPdfTableRow(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_pdf_table_row"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    table_id: uuid.UUID = Field(foreign_key="gwy_pdf_table.id", index=True)
    row_index: int = Field(index=True)
    row_text: str = Field(default="")
    row_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    page: int = Field(index=True)


class GwyChatSession(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_chat_session"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    title: str = Field(default="新会话", max_length=255, index=True)
    last_intent: str | None = Field(default=None, max_length=64, index=True)
    active_topic: str | None = Field(default=None, max_length=255, index=True)
    mentioned_docs: list[str] = Field(default_factory=list, sa_type=JSON)
    summary: str | None = Field(default=None)
    summary_updated_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), index=True
    )


class GwyChatMessage(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_chat_message"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(foreign_key="gwy_chat_session.id", index=True)
    role: str = Field(max_length=32, index=True)
    content: str = Field(default="")
    intent: str | None = Field(default=None, max_length=64, index=True)
    historical_reference: bool = False
    citations: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    retrieval_trace: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyChatAttachment(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_chat_attachment"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(foreign_key="gwy_chat_session.id", index=True)
    file_name: str = Field(max_length=255, index=True)
    original_name: str = Field(max_length=255)
    attachment_type: str = Field(max_length=32, index=True)
    mime_type: str = Field(max_length=128, index=True)
    file_path: str = Field(max_length=1024)
    size_bytes: int = 0
    summary: str | None = Field(default=None)
    extracted_text: str | None = Field(default=None)
    extraction_status: str = Field(default="uploaded", max_length=64, index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyRagCacheEntry(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_rag_cache_entry"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID | None = Field(
        default=None, foreign_key="gwy_chat_session.id", index=True
    )
    query_hash: str = Field(max_length=64, index=True, unique=True)
    request_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    response_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    expires_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), index=True
    )


class GwyRecommendationTask(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_recommendation_task"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    exam_year: int | None = Field(default=None, index=True)
    exam_type: str | None = Field(default=None, max_length=64, index=True)
    target_regions: list[str] = Field(default_factory=list, sa_type=JSON)
    top_k: int = 10
    status: str = Field(default="pending", max_length=32, index=True)
    summary: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyPositionAnalysisSnapshot(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_position_analysis_snapshot"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    title: str = Field(default="岗位分析快照", max_length=255)
    filters_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    selected_position_ids: list[str] = Field(default_factory=list, sa_type=JSON)
    visible_columns: list[str] = Field(default_factory=list, sa_type=JSON)
    notes: str | None = Field(default=None)
    source_sheet: str | None = Field(default=None, max_length=255, index=True)


class GwyPositionAnalysisTask(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_position_analysis_task"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    snapshot_id: uuid.UUID = Field(
        foreign_key="gwy_position_analysis_snapshot.id", index=True
    )
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    status: str = Field(default="pending", max_length=32, index=True)
    stage: str = Field(default="created", max_length=64, index=True)
    input_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    output_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    report_text: str | None = Field(default=None)
    trace_json: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    error_message: str | None = Field(default=None)
    started_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )


class GwyPositionAnalysisStep(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_position_analysis_step"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="gwy_position_analysis_task.id", index=True
    )
    step_name: str = Field(max_length=128)
    status: str = Field(default="running", max_length=32, index=True)
    input_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    output_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    evidence_json: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    error_message: str | None = Field(default=None)
    started_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )


class GwyRecommendationItem(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_recommendation_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(foreign_key="gwy_recommendation_task.id", index=True)
    position_id: uuid.UUID = Field(foreign_key="gwy_position.id", index=True)
    rank: int = Field(index=True)
    score: float = 0.0
    recommend_level: str | None = Field(default=None, max_length=64)
    risk_level: str | None = Field(default=None, max_length=32, index=True)
    competition_level: str | None = Field(default=None, max_length=32)
    need_manual_confirm: bool = False
    reasons: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    risks: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    citations: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)


class GwyRiskItem(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_risk_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(foreign_key="gwy_recommendation_task.id", index=True)
    position_id: uuid.UUID | None = Field(default=None, foreign_key="gwy_position.id")
    risk_type: str = Field(max_length=128, index=True)
    risk_level: str = Field(max_length=32, index=True)
    evidence: str | None = Field(default=None)
    explanation: str | None = Field(default=None)
    suggestion: str | None = Field(default=None)


class GwyAgentRun(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_agent_run"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID | None = Field(
        default=None, foreign_key="gwy_recommendation_task.id", index=True
    )
    graph_name: str = Field(max_length=128, index=True)
    status: str = Field(default="running", max_length=32, index=True)
    input_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    output_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    error_message: str | None = Field(default=None)
    started_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )


class GwyAgentStep(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_agent_step"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_run_id: uuid.UUID = Field(foreign_key="gwy_agent_run.id", index=True)
    step_name: str = Field(max_length=128, index=True)
    status: str = Field(default="running", max_length=32, index=True)
    input_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    output_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    error_message: str | None = Field(default=None)
    started_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )


class GwyToolCall(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_tool_call"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_step_id: uuid.UUID = Field(foreign_key="gwy_agent_step.id", index=True)
    tool_name: str = Field(max_length=128, index=True)
    status: str = Field(default="running", max_length=32, index=True)
    input_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    output_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    latency_ms: int | None = None
    error_message: str | None = Field(default=None)


class GwyConversationMemory(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_conversation_memory"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    conversation_id: str | None = Field(default=None, max_length=128, index=True)
    memory_key: str = Field(max_length=255, index=True)
    memory_value: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    expires_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), index=True
    )


class GwyDecisionMemory(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_decision_memory"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    position_id: uuid.UUID | None = Field(default=None, foreign_key="gwy_position.id")
    decision_type: str = Field(max_length=64, index=True)
    decision_reason: str | None = Field(default=None)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyExperienceMemory(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_experience_memory"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_name: str = Field(max_length=128, index=True)
    scenario: str = Field(max_length=128, index=True)
    trigger: str = Field(max_length=255)
    lesson: str | None = Field(default=None)
    success_count: int = 0
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyHumanReview(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_human_review"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID | None = Field(
        default=None, foreign_key="gwy_recommendation_task.id", index=True
    )
    position_id: uuid.UUID | None = Field(default=None, foreign_key="gwy_position.id")
    review_type: str = Field(max_length=64, index=True)
    status: str = Field(default="pending", max_length=32, index=True)
    review_reason: str | None = Field(default=None)
    reviewer: str | None = Field(default=None, max_length=255)
    review_notes: str | None = Field(default=None)
    decision_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyEvalDataset(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_eval_dataset"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    name: str = Field(max_length=255, index=True)
    version: str = Field(default="1", max_length=64)
    split: str = Field(default="dev", max_length=32, index=True)
    task_type: str = Field(default="e2e", max_length=32, index=True)
    status: str = Field(default="draft", max_length=32, index=True)
    cases_json: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyEvalRun(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_eval_run"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    dataset_id: uuid.UUID | None = Field(default=None, foreign_key="gwy_eval_dataset.id", index=True)
    source_type: str = Field(default="online", max_length=32, index=True)
    source_id: str | None = Field(default=None, max_length=128, index=True)
    task_type: str = Field(default="e2e", max_length=32, index=True)
    status: str = Field(default="running", max_length=32, index=True)
    query: str = Field(default="")
    config_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    summary_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    report_text: str | None = Field(default=None)
    started_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class GwyEvalCaseResult(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_eval_case_result"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="gwy_eval_run.id", index=True)
    case_id: str = Field(max_length=128, index=True)
    status: str = Field(default="failed", max_length=32, index=True)
    passed: bool = False
    scores_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    observation_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    failure_reasons: list[str] = Field(default_factory=list, sa_type=JSON)
    trace_json: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)


# Study Plan models


class GwyStudyPlan(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_study_plan"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    task_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="gwy_position_analysis_task.id",
        index=True,
    )
    title: str = Field(default="????", max_length=255, index=True)
    exam_type: str | None = Field(default=None, max_length=64)
    exam_year: int | None = Field(default=None, index=True)
    estimated_exam_date: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    study_hours_per_day: int = 4
    total_weeks: int = 12
    profile_snapshot: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    position_ids: list[str] = Field(default_factory=list, sa_type=JSON)
    report_markdown: str | None = Field(default=None)
    status: str = Field(default="draft", max_length=32, index=True)


class GwyStudyPhase(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_study_phase"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    study_plan_id: uuid.UUID = Field(foreign_key="gwy_study_plan.id", index=True)
    phase_order: int = 0
    phase_name: str = Field(max_length=128)
    phase_goal: str | None = Field(default=None)
    week_start: int = 1
    week_end: int = 4
    focus_subjects: list[str] = Field(default_factory=list, sa_type=JSON)
    study_hours_per_day: int = 4
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class GwyStudyTask(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_study_task"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    study_plan_id: uuid.UUID = Field(foreign_key="gwy_study_plan.id", index=True)
    phase_id: uuid.UUID | None = Field(default=None, foreign_key="gwy_study_phase.id")
    week_number: int = 1
    day_of_week: int = 1
    subject: str = Field(max_length=128)
    task_title: str = Field(max_length=255)
    task_description: str | None = Field(default=None)
    estimated_minutes: int = 60
    priority: int = 1
    completed: bool = False


class GwyStudySubject(GwyTimestampMixin, table=True):
    __tablename__ = "gwy_study_subject"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    study_plan_id: uuid.UUID = Field(foreign_key="gwy_study_plan.id", index=True)
    subject_name: str = Field(max_length=128, index=True)
    subject_category: str = Field(max_length=64)
    weight_percent: int = 0
    total_hours: int = 0
    checklist_items: list[str] = Field(default_factory=list, sa_type=JSON)
    resources: list[str] = Field(default_factory=list, sa_type=JSON)



Index(
    "ix_gwy_position_analysis_snapshot_title",
    GwyPositionAnalysisSnapshot.title,
)
