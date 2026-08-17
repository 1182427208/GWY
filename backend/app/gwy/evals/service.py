from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.gwy.agents.position_decision_agent import PositionDecisionAgent
from app.gwy.evals.adapters import normalize_agent_output
from app.gwy.evals.online import evaluate_online_observation
from app.gwy.evals.run_eval import load_cases
from app.gwy.evals.schemas import AgentObservation, EvalCase
from app.gwy.llm.chat_service import ChatService
from app.gwy.models import GwyEvalCaseResult, GwyEvalDataset, GwyEvalRun
from app.gwy.services.policy_rag_service import PolicyRagService

_BUILTIN_DATASET_FILES = (
    Path(__file__).resolve().parent / "datasets" / "dev.jsonl",
    Path(__file__).resolve().parent / "datasets" / "holdout.jsonl",
)


def import_builtin_eval_datasets(session: Session) -> list[GwyEvalDataset]:
    """Create or refresh the repository-provided datasets for all users."""
    imported: list[GwyEvalDataset] = []
    for dataset_path in _BUILTIN_DATASET_FILES:
        cases = load_cases(dataset_path)
        if not cases:
            continue
        split_values = {case.split for case in cases}
        task_values = {case.task_type for case in cases}
        split = next(iter(split_values)) if len(split_values) == 1 else "mixed"
        task_type = next(iter(task_values)) if len(task_values) == 1 else "mixed"
        name = f"内置评测集 {dataset_path.stem}"
        dataset = session.exec(
            select(GwyEvalDataset).where(
                GwyEvalDataset.user_id.is_(None),
                GwyEvalDataset.name == name,
            )
        ).first()
        if dataset is None:
            dataset = GwyEvalDataset(user_id=None, name=name)
        dataset.version = "local"
        dataset.split = split
        dataset.task_type = task_type
        dataset.status = "ready" if cases else "draft"
        dataset.cases_json = [case.model_dump() for case in cases]
        dataset.metadata_json = {
            "source_file": str(
                dataset_path.relative_to(Path(__file__).resolve().parent)
            ),
            "template_only": True,
            "ground_truth_binding": "manual",
        }
        session.add(dataset)
        imported.append(dataset)
    session.commit()
    for dataset in imported:
        session.refresh(dataset)
    return imported


def build_online_case(
    *,
    source_type: str,
    source_id: str | None,
    query: str,
    profile: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
) -> EvalCase:
    task_type = "job_filter" if source_type == "position" else "e2e"
    return EvalCase(
        case_id=source_id or f"online-{source_type}",
        task_type=task_type,
        query=query,
        profile=dict(profile or {}),
        expected=dict(expected or {}),
        metadata={"source_type": source_type, "source_id": source_id},
    )


def record_online_evaluation(
    *,
    session: Session,
    user_id: UUID,
    source_type: str,
    source_id: str | None,
    query: str,
    output: Any,
    profile: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case = build_online_case(
        source_type=source_type,
        source_id=source_id,
        query=query,
        profile=profile,
        expected=expected,
    )
    observation = normalize_agent_output(output)
    report = evaluate_online_observation(case, observation)
    run = GwyEvalRun(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        task_type=case.task_type,
        status=report["status"],
        query=query,
        config_json={"mode": "online", "ground_truth": "partial"},
        summary_json={
            "status": report["status"],
            "critical_gate": report["critical_gate"],
            "quality_overview": report["quality_overview"],
            "score_cards": report["score_cards"],
            "trace_complete": report["trace_complete"],
            "failure_reasons": report["failure_reasons"],
        },
        report_text=_render_report(report),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    case_result = GwyEvalCaseResult(
        run_id=run.id,
        case_id=case.case_id,
        status=report["status"],
        passed=report["status"] == "passed",
        scores_json=report["score_cards"],
        observation_json=observation.model_dump(),
        failure_reasons=report["failure_reasons"],
        trace_json=observation.trace,
    )
    session.add(case_result)
    session.commit()
    session.refresh(run)
    return serialize_run(run)


def list_runs(session: Session, user_id: UUID) -> list[dict[str, Any]]:
    rows = session.exec(
        select(GwyEvalRun)
        .where(GwyEvalRun.user_id == user_id)
        .order_by(GwyEvalRun.created_at.desc())
    ).all()
    return [serialize_run(row) for row in rows]


def run_dataset_evaluation(*, session: Session, user_id: UUID, dataset: GwyEvalDataset) -> dict[str, Any]:
    run = GwyEvalRun(
        user_id=user_id,
        dataset_id=dataset.id,
        source_type="dataset",
        task_type=dataset.task_type,
        status="running",
        config_json={"dataset_version": dataset.version, "split": dataset.split},
    )
    session.add(run)
    session.flush()
    reports: list[dict[str, Any]] = []
    for raw_case in dataset.cases_json or []:
        case = EvalCase.model_validate(raw_case)
        try:
            output = _run_case(session, user_id, case)
            report = evaluate_online_observation(case, normalize_agent_output(output))
        except Exception as exc:
            report = {
                "status": "failed",
                "trace_complete": False,
                "scores": {},
                "failure_reasons": [f"agent execution failed: {exc}"],
                "observation": AgentObservation(status="error").model_dump(),
            }
        observation_data = dict(report["observation"])
        session.add(GwyEvalCaseResult(
            run_id=run.id,
            case_id=case.case_id,
            status=report["status"],
            passed=report["status"] == "passed",
            scores_json=report["scores"],
            observation_json=observation_data,
            failure_reasons=report["failure_reasons"],
            trace_json=list(observation_data.get("trace") or []),
        ))
        reports.append(report)
    passed = sum(1 for item in reports if item["status"] == "passed")
    blocked = sum(1 for item in reports if item["status"] == "blocked")
    run.status = "passed" if passed == len(reports) else ("blocked" if blocked else "failed")
    run.summary_json = {
        "case_count": len(reports),
        "passed_count": passed,
        "failed_count": len(reports) - passed,
        "blocked_count": blocked,
        "task_success_rate": passed / len(reports) if reports else 0.0,
        "trace_complete_count": sum(1 for item in reports if item["trace_complete"]),
        "critical_gate_pass_rate": (
            sum(1 for item in reports if item["critical_gate"]["passed"]) / len(reports)
            if reports
            else 0.0
        ),
        "quality_overview": _aggregate_quality_overview(reports),
        "score_cards": _aggregate_score_cards(reports),
    }
    run.report_text = _render_batch_report(run.summary_json)
    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
    session.refresh(run)
    return serialize_run(run)


def _run_case(session: Session, user_id: UUID, case: EvalCase) -> Any:
    metadata = case.metadata
    year = int(metadata.get("year") or 2026)
    exam_type = str(metadata.get("exam_type") or "national")
    top_k = int(metadata.get("top_k") or 5)
    if case.task_type == "job_filter":
        return PositionDecisionAgent(session=session, chat_service=ChatService()).run(
            query=case.query,
            user_id=user_id,
            year=year,
            exam_type=exam_type,
            top_k=top_k,
            persist_result=False,
            profile_override=case.profile,
        )
    return PolicyRagService(session=session).query_policy(
        query=case.query,
        year=year,
        exam_type=exam_type,
        top_k=top_k,
        use_rerank=True,
        mode="policy_rag",
    )


def get_run(session: Session, run_id: UUID, user_id: UUID) -> GwyEvalRun | None:
    run = session.get(GwyEvalRun, run_id)
    return run if run and run.user_id == user_id else None


def serialize_run(run: GwyEvalRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "dataset_id": run.dataset_id,
        "source_type": run.source_type,
        "source_id": run.source_id,
        "task_type": run.task_type,
        "status": run.status,
        "query": run.query,
        "config": dict(run.config_json or {}),
        "summary": dict(run.summary_json or {}),
        "report_text": run.report_text,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _render_report(report: dict[str, Any]) -> str:
    lines = [
        "# GwyPilot 在线评测报告",
        "",
        f"- 状态：{report['status']}",
        f"- Critical Gate：{'通过' if report['critical_gate']['passed'] else '未通过'}",
        f"- 完整 trace：{'是' if report['trace_complete'] else '否'}",
        "",
        "## 分层指标",
        "",
    ]
    for name, score in report["score_cards"].items():
        lines.append(f"### {name}")
        lines.append(f"- 通过：{score['passed']}")
        for key, value in score["metrics"].items():
            lines.append(f"- {key}：{value}")
    if report["failure_reasons"]:
        lines.extend(["", "## 失败原因", ""])
        lines.extend(f"- {reason}" for reason in report["failure_reasons"])
    return "\n".join(lines)


def _render_batch_report(summary: dict[str, Any]) -> str:
    return "\n".join([
        "# GwyPilot 数据集评测报告",
        "",
        f"- case 数：{summary.get('case_count', 0)}",
        f"- 通过：{summary.get('passed_count', 0)}",
        f"- 失败：{summary.get('failed_count', 0)}",
        f"- 阻塞：{summary.get('blocked_count', 0)}",
        f"- 任务成功率：{summary.get('task_success_rate', 0)}",
        f"- 完整 trace 数：{summary.get('trace_complete_count', 0)}",
    ])


def _aggregate_quality_overview(reports: list[dict[str, Any]]) -> dict[str, Any]:
    quality: dict[str, dict[str, list[float]]] = {}
    for report in reports:
        for section_name, payload in dict(report.get("quality_overview") or {}).items():
            section = quality.setdefault(section_name, {})
            for metric_name, value in dict(payload or {}).items():
                if isinstance(value, (int, float)):
                    section.setdefault(metric_name, []).append(float(value))
    return {
        section_name: {
            metric_name: sum(values) / len(values)
            for metric_name, values in sorted(metrics.items())
            if values
        }
        for section_name, metrics in quality.items()
    }


def _aggregate_score_cards(reports: list[dict[str, Any]]) -> dict[str, Any]:
    aggregated: dict[str, dict[str, Any]] = {}
    for report in reports:
        for name, score in dict(report.get("score_cards") or {}).items():
            card = aggregated.setdefault(
                name,
                {"case_count": 0, "passed_count": 0, "metrics": {}},
            )
            card["case_count"] += 1
            card["passed_count"] += 1 if score.get("passed") else 0
            metric_bucket = card["metrics"].setdefault("_", {})
            for metric_name, value in dict(score.get("metrics") or {}).items():
                if isinstance(value, (int, float)):
                    metric_bucket.setdefault(metric_name, []).append(float(value))
    for card in aggregated.values():
        metrics = card["metrics"].pop("_", {})
        card["pass_rate"] = card["passed_count"] / card["case_count"] if card["case_count"] else 0.0
        card["metrics"] = {
            metric_name: sum(values) / len(values)
            for metric_name, values in sorted(metrics.items())
            if values
        }
    return aggregated
