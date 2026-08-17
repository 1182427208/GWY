from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import CurrentUser, SessionDep
from app.core.db import engine
from app.gwy.evals.service import record_online_evaluation
from app.gwy.llm.chat_service import ChatService
from app.gwy.models import (
    GwyPositionAnalysisSnapshot,
    GwyPositionAnalysisTask,
)
from app.gwy.services.position_analysis_service import PositionAnalysisService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gwy/analysis", tags=["gwy-analysis"])


class PositionAnalysisTaskCreateRequest(BaseModel):
    snapshot: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    source_sheet: str | None = None
    notes: str | None = None
    enable_evaluation: bool = False


class PositionAnalysisSnapshotResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    source_sheet: str | None = None
    filters_json: dict[str, Any] = Field(default_factory=dict)
    snapshot_json: dict[str, Any] = Field(default_factory=dict)
    selected_position_ids: list[str] = Field(default_factory=list)
    visible_columns: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: datetime | None = None


class PositionAnalysisTaskResponse(BaseModel):
    id: UUID
    snapshot_id: UUID
    user_id: UUID
    status: str
    stage: str
    input_json: dict[str, Any] = Field(default_factory=dict)
    output_json: dict[str, Any] = Field(default_factory=dict)
    report_text: str | None = None
    trace_json: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class PositionAnalysisTaskRunResponse(BaseModel):
    status: str
    task_id: UUID
    snapshot_id: UUID
    task: PositionAnalysisTaskResponse
    snapshot: PositionAnalysisSnapshotResponse
    report: str | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)


class PositionAnalysisTraceResponse(BaseModel):
    task_id: UUID
    status: str
    stage: str
    trace: list[dict[str, Any]] = Field(default_factory=list)


class PositionAnalysisReportResponse(BaseModel):
    task_id: UUID
    status: str
    stage: str
    report: str | None = None
    report_text: str | None = None


@router.post("/tasks", response_model=PositionAnalysisTaskRunResponse)
def create_position_analysis_task(
    payload: PositionAnalysisTaskCreateRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionAnalysisTaskRunResponse:
    snapshot_payload = dict(payload.snapshot)
    if payload.title is not None:
        snapshot_payload["title"] = payload.title
    if payload.source_sheet is not None:
        snapshot_payload["source_sheet"] = payload.source_sheet
    if payload.notes is not None:
        snapshot_payload["notes"] = payload.notes
    snapshot_payload["enable_evaluation"] = payload.enable_evaluation

    service = PositionAnalysisService(session=session, chat_service=ChatService())
    result = service.create_task(snapshot=snapshot_payload, user_id=current_user.id)
    background_tasks.add_task(
        _run_position_analysis_task_background,
        str(result["snapshot_id"]),
        str(result["task_id"]),
        str(current_user.id),
    )
    return PositionAnalysisTaskRunResponse(
        status="running",
        task_id=UUID(str(result["task_id"])),
        snapshot_id=UUID(str(result["snapshot_id"])),
        task=PositionAnalysisTaskResponse.model_validate(result["task"]),
        snapshot=PositionAnalysisSnapshotResponse.model_validate(result["snapshot"]),
        report=None,
        trace=[],
    )


@router.get("/tasks/{task_id}", response_model=PositionAnalysisTaskResponse)
def get_position_analysis_task(
    task_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionAnalysisTaskResponse:
    task = _get_task_or_404(session, task_id, current_user.id)
    return PositionAnalysisTaskResponse.model_validate(_serialize_task(task))


@router.get("/tasks/{task_id}/trace", response_model=PositionAnalysisTraceResponse)
def get_position_analysis_task_trace(
    task_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionAnalysisTraceResponse:
    task = _get_task_or_404(session, task_id, current_user.id)
    return PositionAnalysisTraceResponse(
        task_id=task.id,
        status=task.status,
        stage=task.stage,
        trace=list(task.trace_json or []),
    )


@router.get("/tasks/{task_id}/report", response_model=PositionAnalysisReportResponse)
def get_position_analysis_task_report(
    task_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionAnalysisReportResponse:
    task = _get_task_or_404(session, task_id, current_user.id)
    return PositionAnalysisReportResponse(
        task_id=task.id,
        status=task.status,
        stage=task.stage,
        report=task.report_text,
        report_text=task.report_text,
    )


@router.get("/snapshots/{snapshot_id}", response_model=PositionAnalysisSnapshotResponse)
def get_position_analysis_snapshot(
    snapshot_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> PositionAnalysisSnapshotResponse:
    snapshot = _get_snapshot_or_404(session, snapshot_id, current_user.id)
    return PositionAnalysisSnapshotResponse.model_validate(_serialize_snapshot(snapshot))


def _get_task_or_404(
    session: SessionDep,
    task_id: UUID,
    user_id: UUID,
) -> GwyPositionAnalysisTask:
    task = session.get(GwyPositionAnalysisTask, task_id)
    if task is None or task.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position analysis task not found: {task_id}",
        )
    return task


def _get_snapshot_or_404(
    session: SessionDep,
    snapshot_id: UUID,
    user_id: UUID,
) -> GwyPositionAnalysisSnapshot:
    snapshot = session.get(GwyPositionAnalysisSnapshot, snapshot_id)
    if snapshot is None or snapshot.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position analysis snapshot not found: {snapshot_id}",
        )
    return snapshot


def _serialize_task(task: GwyPositionAnalysisTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "snapshot_id": task.snapshot_id,
        "user_id": task.user_id,
        "status": task.status,
        "stage": task.stage,
        "input_json": dict(task.input_json or {}),
        "output_json": dict(task.output_json or {}),
        "report_text": task.report_text,
        "trace_json": list(task.trace_json or []),
        "error_message": task.error_message,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "created_at": task.created_at,
    }


def _serialize_snapshot(snapshot: GwyPositionAnalysisSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "user_id": snapshot.user_id,
        "title": snapshot.title,
        "source_sheet": snapshot.source_sheet,
        "filters_json": dict(snapshot.filters_json or {}),
        "snapshot_json": dict(snapshot.snapshot_json or {}),
        "selected_position_ids": list(snapshot.selected_position_ids or []),
        "visible_columns": list(snapshot.visible_columns or []),
        "notes": snapshot.notes,
        "created_at": snapshot.created_at,
    }


def _run_position_analysis_task_background(
    snapshot_id: str,
    task_id: str,
    user_id: str,
    database_engine: Any | None = None,
) -> None:
    selected_engine = database_engine or engine
    try:
        with Session(selected_engine) as background_session:
            service = PositionAnalysisService(
                session=background_session,
                chat_service=ChatService(),
            )
            service.execute_existing_task(
                snapshot_id=snapshot_id,
                task_id=task_id,
                user_id=user_id,
            )
            task = background_session.get(GwyPositionAnalysisTask, UUID(task_id))
            if task is not None and bool((task.input_json or {}).get("enable_evaluation")):
                record_online_evaluation(
                    session=background_session,
                    user_id=UUID(user_id),
                    source_type="position_analysis",
                    source_id=task_id,
                    query=str((task.input_json or {}).get("query") or ""),
                    output={
                        "answer": task.report_text or "",
                        "report": task.report_text or "",
                        "recommendations": (task.output_json or {}).get("recommendations", []),
                        "trace": task.trace_json or [],
                        "status": task.status,
                    },
                )
    except Exception as exc:
        logger.exception(
            "Position analysis background task failed",
            extra={
                "snapshot_id": snapshot_id,
                "task_id": task_id,
                "user_id": user_id,
            },
        )
        try:
            with Session(selected_engine) as fail_session:
                task = fail_session.get(GwyPositionAnalysisTask, UUID(task_id))
                if task is not None:
                    task.status = "failed"
                    task.stage = "failed"
                    task.error_message = str(exc)
                    task.finished_at = datetime.now(timezone.utc)
                    fail_session.add(task)
                    fail_session.commit()
        except Exception:
            logger.exception(
                "Failed to persist background task failure",
                extra={
                    "snapshot_id": snapshot_id,
                    "task_id": task_id,
                    "user_id": user_id,
                },
            )
        return
