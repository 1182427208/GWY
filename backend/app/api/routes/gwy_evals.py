from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.gwy.evals.schemas import EvalCase
from app.gwy.evals.service import (
    get_run,
    import_builtin_eval_datasets,
    list_runs,
    record_online_evaluation,
    run_dataset_evaluation,
    serialize_run,
)
from app.gwy.models import GwyEvalCaseResult, GwyEvalDataset

router = APIRouter(prefix="/gwy/evals", tags=["gwy-evals"])


class EvalDatasetCreateRequest(BaseModel):
    name: str
    version: str = "1"
    split: str = "dev"
    task_type: str = "e2e"
    cases: list[dict[str, Any]] = Field(default_factory=list)


class EvalDatasetResponse(BaseModel):
    id: UUID
    name: str
    version: str
    split: str
    task_type: str
    status: str
    case_count: int
    cases: list[dict[str, Any]] = Field(default_factory=list)


class EvalRunCreateRequest(BaseModel):
    dataset_id: UUID | None = None
    source_type: str = "online"
    source_id: str | None = None
    query: str = ""
    output: dict[str, Any] | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)


class EvalRunResponse(BaseModel):
    id: UUID
    dataset_id: UUID | None = None
    source_type: str
    source_id: str | None = None
    task_type: str
    status: str
    query: str
    config: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    report_text: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@router.post("/datasets/import-defaults", response_model=list[EvalDatasetResponse])
def import_default_eval_datasets(session: SessionDep, current_user: CurrentUser):
    del current_user
    return [_serialize_dataset(row) for row in import_builtin_eval_datasets(session)]


@router.get("/datasets", response_model=list[EvalDatasetResponse])
def get_eval_datasets(session: SessionDep, current_user: CurrentUser):
    rows = session.exec(
        select(GwyEvalDataset)
        .where((GwyEvalDataset.user_id == current_user.id) | (GwyEvalDataset.user_id.is_(None)))
        .order_by(GwyEvalDataset.created_at.desc())
    ).all()
    return [_serialize_dataset(row) for row in rows]


@router.post("/datasets", response_model=EvalDatasetResponse)
def create_eval_dataset(
    payload: EvalDatasetCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    cases = [EvalCase.model_validate(item).model_dump() for item in payload.cases]
    dataset = GwyEvalDataset(
        user_id=current_user.id,
        name=payload.name,
        version=payload.version,
        split=payload.split,
        task_type=payload.task_type,
        status="ready" if cases else "draft",
        cases_json=cases,
    )
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return _serialize_dataset(dataset)


@router.get("/runs", response_model=list[EvalRunResponse])
def get_eval_runs(session: SessionDep, current_user: CurrentUser):
    return list_runs(session, current_user.id)


@router.post("/datasets/{dataset_id}/runs", response_model=EvalRunResponse)
def run_eval_dataset(
    dataset_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
):
    dataset = session.get(GwyEvalDataset, dataset_id)
    if dataset is None or dataset.user_id not in {None, current_user.id}:
        raise HTTPException(status_code=404, detail="Evaluation dataset not found")
    return run_dataset_evaluation(session=session, user_id=current_user.id, dataset=dataset)


@router.post("/runs", response_model=EvalRunResponse)
def create_eval_run(
    payload: EvalRunCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    if payload.output is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Online evaluation requires the completed agent output.",
        )
    result = record_online_evaluation(
        session=session,
        user_id=current_user.id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        query=payload.query,
        output=payload.output,
        profile=payload.profile,
        expected=payload.expected,
    )
    return result


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
def get_eval_run(run_id: UUID, session: SessionDep, current_user: CurrentUser):
    run = get_run(session, run_id, current_user.id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return serialize_run(run)


@router.get("/runs/{run_id}/cases")
def get_eval_run_cases(run_id: UUID, session: SessionDep, current_user: CurrentUser):
    run = get_run(session, run_id, current_user.id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    rows = session.exec(
        select(GwyEvalCaseResult).where(GwyEvalCaseResult.run_id == run_id)
    ).all()
    return [
        {
            "id": row.id,
            "case_id": row.case_id,
            "status": row.status,
            "passed": row.passed,
            "scores": row.scores_json,
            "observation": row.observation_json,
            "failure_reasons": row.failure_reasons,
            "trace": row.trace_json,
        }
        for row in rows
    ]


def _serialize_dataset(dataset: GwyEvalDataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "version": dataset.version,
        "split": dataset.split,
        "task_type": dataset.task_type,
        "status": dataset.status,
        "case_count": len(dataset.cases_json or []),
        "cases": list(dataset.cases_json or []),
    }
