from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskType = Literal["job_filter", "policy_qa", "tool_call", "memory", "e2e"]


class ExpectedOutcome(BaseModel):
    expected_position: dict[str, Any] = Field(default_factory=dict)
    job_ids: list[str] = Field(default_factory=list)
    forbidden_job_ids: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    tool_arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    forbidden_arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    maximum_tool_calls: int | None = None
    expected_final_status: str | None = None
    gold_doc_ids: list[str] = Field(default_factory=list)
    gold_chunk_ids: list[str] = Field(default_factory=list)
    gold_answer_points: list[str] = Field(default_factory=list)
    memory_after: dict[str, Any] = Field(default_factory=dict)
    should_ask_clarification: bool = False
    report_required: bool = False
    feishu_required: bool = False


class EvalCase(BaseModel):
    case_id: str
    task_type: TaskType
    query: str
    split: str = "dev"
    difficulty: str = "normal"
    conversation: list[dict[str, Any]] = Field(default_factory=list)
    initial_memory: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)
    expected: ExpectedOutcome = Field(default_factory=ExpectedOutcome)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    latency_ms: int | None = None
    error: str | None = None


class AgentObservation(BaseModel):
    final_answer: str = ""
    status: str = "success"
    task_contract: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    resolved_position: dict[str, Any] = Field(default_factory=dict)
    returned_job_ids: list[str] = Field(default_factory=list)
    returned_jobs: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_documents: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    memory_before: dict[str, Any] = Field(default_factory=dict)
    memory_after: dict[str, Any] = Field(default_factory=dict)
    memory_leakage_count: int = 0
    stale_field_usage_count: int = 0
    memory_update_accuracy: float | None = None
    agent_steps: int = 0
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    raw_output: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class EvalConfig(BaseModel):
    experiment_name: str = "gwy_agent_eval"
    dataset_split: str = "dev"
    model: str = "unavailable"
    temperature: float = 0
    prompt_version: str = "unavailable"
    knowledge_version: str = "unavailable"
    job_table_version: str = "unavailable"
    top_k: int = 5
    max_agent_steps: int = 10
    enable_multi_agent: bool = True
    enable_memory: bool = True
    enable_web_verification: bool = False
    enable_llm_judge: bool = False
    mock_external_services: bool = True
    dataset_version: str = "local"
    git_commit: str = "unavailable"
    output_format_version: str = "1"


class ScoreBundle(BaseModel):
    name: str
    passed: bool
    metrics: dict[str, float | int | str | None] = Field(default_factory=dict)
    failure_reasons: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class CaseResult(BaseModel):
    case_id: str
    task_type: str
    passed: bool
    scores: list[ScoreBundle]
    observation: AgentObservation
    failure_reasons: list[str] = Field(default_factory=list)
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    config: dict[str, Any] = Field(default_factory=dict)
