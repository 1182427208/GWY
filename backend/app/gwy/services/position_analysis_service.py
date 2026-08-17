from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.core.config import settings
from app.gwy.agents.feishu_push_agent import FeishuPushAgent
from app.gwy.agents.position_decision_agent import PositionDecisionAgent
from app.gwy.agents.position_analysis_agent import PositionAnalysisAgent
from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
from app.gwy.agents.risk_review_agent import RiskReviewAgent
from app.gwy.llm.chat_service import ChatService
from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.llm.rerank_service import RerankService
from app.gwy.models import (
    GwyPositionAnalysisSnapshot,
    GwyPositionAnalysisStep,
    GwyPositionAnalysisTask,
    GwyRecommendationItem,
    GwyUserProfile,
    get_datetime_utc,
)
from app.gwy.services.agent_memory_service import AgentMemoryService
from app.gwy.services.long_term_memory_service import LongTermMemoryService
from app.gwy.services.playwright_mcp_service import PlaywrightMCPService
from app.gwy.services.position_catalog_service import PositionCatalogService
from app.gwy.services.position_snapshot_runtime_service import (
    PositionSnapshotRuntimeService,
)
from app.gwy.services.study_plan_service import StudyPlanService
from app.gwy.services.web_fetch_service import WebFetchService
from app.gwy.services.web_search_service import WebSearchService
from app.gwy.skills.position_analysis_skills import normalize_analysis_snapshot
from app.gwy.skills.position_recommendation_skills import build_profile_summary
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore
import logging


logger = logging.getLogger(__name__)


class PositionAnalysisService:
    def __init__(
        self,
        *,
        session: Session,
        decision_agent: PositionDecisionAgent | None = None,
        agent: PositionAnalysisAgent | None = None,
        position_catalog_service: PositionCatalogService | None = None,
        embedding_service: EmbeddingService | None = None,
        rerank_service: RerankService | None = None,
        milvus_store: MilvusPolicyStore | None = None,
        web_search_service: WebSearchService | None = None,
        web_fetch_service: WebFetchService | None = None,
        browser_service: PlaywrightMCPService | None = None,
        risk_review_agent: RiskReviewAgent | None = None,
        report_generator_agent: ReportGeneratorAgent | None = None,
        feishu_push_agent: FeishuPushAgent | None = None,
        chat_service: ChatService | None = None,
        snapshot_runtime_service_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.session = session
        self.decision_agent = decision_agent or PositionDecisionAgent(session=session)
        self.agent = agent or PositionAnalysisAgent(
            session=session,
            position_catalog_service=position_catalog_service,
            embedding_service=embedding_service,
            rerank_service=rerank_service,
            milvus_store=milvus_store,
            web_search_service=web_search_service,
            web_fetch_service=web_fetch_service,
            browser_service=browser_service,
            risk_review_agent=risk_review_agent,
            report_generator_agent=report_generator_agent,
            chat_service=chat_service,
        )
        self.feishu_push_agent = feishu_push_agent or FeishuPushAgent()
        self.snapshot_runtime_service_factory = snapshot_runtime_service_factory

    def run(
        self,
        *,
        snapshot: dict[str, Any],
        user_id: UUID | str,
    ) -> dict[str, Any]:
        prepared = self.create_task(snapshot=snapshot, user_id=user_id)
        return self.execute_existing_task(
            snapshot_id=prepared["snapshot_id"],
            task_id=prepared["task_id"],
            user_id=user_id,
        )

    def create_task(
        self,
        *,
        snapshot: dict[str, Any],
        user_id: UUID | str,
    ) -> dict[str, Any]:
        user_uuid = UUID(str(user_id))
        normalized_snapshot = normalize_analysis_snapshot(snapshot)
        user_profile = self._load_user_profile(user_uuid)
        snapshot_row = GwyPositionAnalysisSnapshot(
            user_id=user_uuid,
            title=str(normalized_snapshot.get("title") or "岗位分析快照"),
            source_sheet=str(normalized_snapshot.get("source_sheet") or ""),
            filters_json=dict(normalized_snapshot.get("filters_json") or {}),
            snapshot_json=dict(normalized_snapshot.get("snapshot_json") or {}),
            selected_position_ids=list(
                normalized_snapshot.get("selected_position_ids") or []
            ),
            visible_columns=list(normalized_snapshot.get("visible_columns") or []),
            notes=str(normalized_snapshot.get("notes") or ""),
        )
        task_row = GwyPositionAnalysisTask(
            snapshot_id=snapshot_row.id,
            user_id=user_uuid,
            status="running",
            stage="queued",
            input_json={
                "user_id": str(user_uuid),
                "snapshot": normalized_snapshot,
                "user_profile": user_profile,
            },
        )

        self.session.add(snapshot_row)
        self.session.add(task_row)
        self.session.commit()
        self.session.refresh(snapshot_row)
        self.session.refresh(task_row)
        return {
            "snapshot": self._serialize_snapshot(snapshot_row),
            "task": self._serialize_task(task_row),
            "snapshot_id": str(snapshot_row.id),
            "task_id": str(task_row.id),
        }

    def execute_existing_task(
        self,
        *,
        snapshot_id: UUID | str,
        task_id: UUID | str,
        user_id: UUID | str,
    ) -> dict[str, Any]:
        snapshot_uuid = UUID(str(snapshot_id))
        task_uuid = UUID(str(task_id))
        user_uuid = UUID(str(user_id))
        snapshot_row = self.session.get(GwyPositionAnalysisSnapshot, snapshot_uuid)
        task_row = self.session.get(GwyPositionAnalysisTask, task_uuid)
        if snapshot_row is None or task_row is None:
            raise ValueError("Position analysis task or snapshot not found.")
        if snapshot_row.user_id != user_uuid or task_row.user_id != user_uuid:
            raise ValueError("Position analysis task ownership mismatch.")
        if task_row.snapshot_id != snapshot_row.id:
            raise ValueError("Position analysis task snapshot mismatch.")

        user_profile = self._load_user_profile(user_uuid)
        return self._execute_task(
            snapshot_row=snapshot_row,
            task_row=task_row,
            user_uuid=user_uuid,
            user_profile=user_profile,
        )

    def _execute_task(
        self,
        *,
        snapshot_row: GwyPositionAnalysisSnapshot,
        task_row: GwyPositionAnalysisTask,
        user_uuid: UUID,
        user_profile: dict[str, Any],
    ) -> dict[str, Any]:
        task_row.status = "running"
        task_row.stage = "load_snapshot"
        self.session.add(task_row)
        self.session.commit()

        recommendation_context = self._build_recommendation_context(
            snapshot_row=snapshot_row,
            user_uuid=user_uuid,
            user_profile=user_profile,
        )
        task_row.input_json = {
            **dict(task_row.input_json or {}),
            "recommendation_context": recommendation_context,
        }
        self.session.add(task_row)
        self.session.commit()

        # Build memory context best-effort only; this must never block analysis.
        enriched_profile = dict(user_profile or {})
        try:
            memory_service = AgentMemoryService(
                session=self.session,
                user_id=user_uuid,
                conversation_id=str(task_row.id),
            )
            memory_service.save_task_context(
                {
                    "task_id": str(task_row.id),
                    "snapshot_id": str(snapshot_row.id),
                    "stage": "starting",
                }
            )
            memory_prompt = memory_service.build_memory_prompt()
            if memory_prompt:
                enriched_profile["_memory_context"] = memory_prompt
        except Exception:
            logger.exception("Failed to build memory context for analysis task")

        try:
            result = self._run_agent_analysis(
                snapshot_row=snapshot_row,
                task_row=task_row,
                user_uuid=user_uuid,
                user_profile=enriched_profile,
                recommendation_context=recommendation_context,
            )
        except Exception as exc:
            task_row.status = "failed"
            task_row.stage = "failed"
            task_row.error_message = str(exc)
            task_row.finished_at = get_datetime_utc()
            self.session.add(task_row)
            self.session.commit()
            raise

        study_plan_result = self._build_study_plan_result(
            user_uuid=user_uuid,
            task_id=task_row.id,
            user_profile=enriched_profile,
            recommendations=list(result.get("recommendations") or []),
            recommendation_context=recommendation_context,
        )
        if study_plan_result is not None:
            result["output_json"] = {
                **dict(result.get("output_json") or {}),
                "study_plan": study_plan_result,
            }

        self._persist_steps(task_row.id, list(result.get("trace") or []))
        self._update_task_from_result(task_row, result)
        # Record memory after analysis
        try:
            ltm_service = LongTermMemoryService(session=self.session)
            ltm_service.record_agent_experience(
                agent_name="position_analysis",
                scenario="full_analysis",
                trigger=str(snapshot_row.title or "analysis"),
                lesson="completed",
                success=True,
            )
            # Record position decisions from recommendations
            for rec in (result.get("recommendations") or []):
                if rec.get("position_id"):
                    from uuid import UUID as _UUID
                    try:
                        pid = _UUID(str(rec["position_id"]))
                        ltm_service.record_position_decision(
                            user_id=user_uuid,
                            position_id=pid,
                            decision_type="view",
                            metadata={
                                "job_title": rec.get("job_title", ""),
                                "department_name": rec.get("department_name", ""),
                            },
                        )
                    except (ValueError, TypeError):
                        pass
            # Save analysis progress for future reference
            memory_service.save_analysis_progress({
                "stage": "completed",
                "result_summary": str(result.get("answer", ""))[:200],
            })
        except Exception:
            logger.exception("Failed to record long-term memory")
        self.session.add(task_row)
        self.session.commit()
        feishu_push_result = None
        if str(task_row.status) != "needs_more_info":
            feishu_push_result = self._push_report_to_feishu(task_row, result)
        if feishu_push_result is not None:
            self.session.add(task_row)
            self.session.commit()
        self.session.refresh(snapshot_row)
        self.session.refresh(task_row)

        return {
            **result,
            "feishu_push": feishu_push_result,
            "snapshot": self._serialize_snapshot(snapshot_row),
            "task": self._serialize_task(task_row),
            "snapshot_id": str(snapshot_row.id),
            "task_id": str(task_row.id),
        }

    def _run_agent_analysis(
        self,
        *,
        snapshot_row: GwyPositionAnalysisSnapshot,
        task_row: GwyPositionAnalysisTask,
        user_uuid: UUID,
        user_profile: dict[str, Any],
        recommendation_context: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._run_snapshot_runtime_analysis(
                snapshot_row=snapshot_row,
                task_row=task_row,
                user_uuid=user_uuid,
                user_profile=user_profile,
                recommendation_context=recommendation_context,
            )
        except Exception:
            logger.exception(
                "Snapshot runtime failed; falling back to legacy position analysis agent"
            )
            result = self.agent.run(
                snapshot_id=snapshot_row.id,
                user_id=user_uuid,
                task_id=task_row.id,
                user_profile=user_profile,
                recommendation_context=recommendation_context,
            )
            result["trace"] = [
                {
                    "step": "snapshot_runtime_fallback",
                    "status": "done",
                    "detail": (
                        "Snapshot AgentRuntime failed; legacy "
                        "PositionAnalysisAgent completed the task."
                    ),
                },
                *list(result.get("trace") or []),
            ]
            return result

    def _run_snapshot_runtime_analysis(
        self,
        *,
        snapshot_row: GwyPositionAnalysisSnapshot,
        task_row: GwyPositionAnalysisTask,
        user_uuid: UUID,
        user_profile: dict[str, Any],
        recommendation_context: dict[str, Any],
    ) -> dict[str, Any]:
        factory = self.snapshot_runtime_service_factory
        runtime_service = (
            factory(session=self.session)
            if factory is not None
            else PositionSnapshotRuntimeService(
                session=self.session,
                chat_service=getattr(self.agent, "chat_service", None),
                on_event=self._build_runtime_trace_callback(task_row),
            )
        )
        return runtime_service.run(
            snapshot=self._serialize_snapshot(snapshot_row),
            user_id=user_uuid,
            task_id=task_row.id,
            user_profile=user_profile,
            recommendation_context=recommendation_context,
        )

    def _build_runtime_trace_callback(
        self,
        task_row: GwyPositionAnalysisTask,
    ) -> Callable[[dict[str, Any]], None]:
        def record(event: dict[str, Any]) -> None:
            task_row.trace_json = [
                *list(task_row.trace_json or []),
                self._normalize_runtime_trace_event(event),
            ]
            self.session.add(task_row)
            self.session.commit()

        return record

    def _normalize_runtime_trace_event(self, event: dict[str, Any]) -> dict[str, Any]:
        step = str(event.get("step") or event.get("tool") or event.get("event") or "")
        return {
            "event": str(event.get("event") or ""),
            "step": step,
            "tool": event.get("tool"),
            "status": str(event.get("status") or "done"),
            "detail": str(event.get("detail") or ""),
            "input": dict(event.get("input") or {}),
            "output": dict(event.get("output") or {}),
            "elapsed_ms": int(event.get("elapsed_ms") or 0),
            "turn": event.get("turn"),
        }

    def _build_study_plan_result(
        self,
        *,
        user_uuid: UUID,
        task_id: UUID,
        user_profile: dict[str, Any],
        recommendations: list[dict[str, Any]],
        recommendation_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            exam_year = self._extract_exam_year(
                recommendation_context=recommendation_context,
                user_profile=user_profile,
            )
            exam_type = self._extract_exam_type(recommendation_context)
            study_hours_per_day = self._extract_study_hours(user_profile)
            service = StudyPlanService(session=self.session)
            result = service.generate(
                user_id=user_uuid,
                user_profile=user_profile,
                recommendations=recommendations,
                task_id=task_id,
                exam_type=exam_type,
                exam_year=exam_year,
                study_hours_per_day=study_hours_per_day,
                push_to_feishu=False,
            )
        except Exception:
            logger.exception("Failed to generate study plan from analysis result")
            return {
                "status": "failed",
                "error_message": "study plan generation failed",
            }

        return {
            "status": "completed",
            **result,
        }

    def _build_recommendation_context(
        self,
        *,
        snapshot_row: GwyPositionAnalysisSnapshot,
        user_uuid: UUID,
        user_profile: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = self._serialize_snapshot(snapshot_row)
        filters = dict(snapshot.get("filters_json") or {})
        query_parts = [
            str(snapshot.get("title") or "").strip(),
            str(snapshot.get("notes") or "").strip(),
            str(user_profile.get("major") or "").strip(),
            str(user_profile.get("education") or "").strip(),
            str(user_profile.get("degree") or "").strip(),
            " ".join(list(user_profile.get("target_regions") or [])),
        ]
        query = " ".join(part for part in query_parts if part).strip()
        query = query or str(snapshot.get("title") or "岗位分析").strip()
        year = int(filters.get("year") or 2026)
        exam_type = str(filters.get("exam_type") or "national").strip() or "national"
        top_k = min(max(len(snapshot_row.selected_position_ids or []) or 5, 3), 8)

        try:
            decision_result = self.decision_agent.run(
                query=query,
                user_id=user_uuid,
                year=year,
                exam_type=exam_type,
                top_k=top_k,
                persist_result=False,
                profile_override=user_profile,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "query": query,
                "year": year,
                "exam_type": exam_type,
                "top_k": top_k,
                "error_message": str(exc),
                "recommendations": [],
                "summary": {},
                "retrieval_trace": [],
            }

        recommendations = list(decision_result.get("recommendations") or [])
        summary = dict(decision_result.get("summary") or {})
        return {
            "status": "completed",
            "query": query,
            "year": year,
            "exam_type": exam_type,
            "top_k": top_k,
            "need_more_info": bool(decision_result.get("need_more_info")),
            "missing_fields": list(decision_result.get("missing_fields") or []),
            "answer": str(decision_result.get("answer") or ""),
            "summary": summary,
            "recommendations": recommendations,
            "task_id": decision_result.get("task_id"),
            "retrieval_trace": list(decision_result.get("retrieval_trace") or []),
        }

    def _persist_steps(
        self,
        task_id: UUID,
        trace: list[dict[str, Any]],
    ) -> None:
        for entry in trace:
            self.session.add(
                GwyPositionAnalysisStep(
                    task_id=task_id,
                    step_name=str(entry.get("step") or ""),
                    status=str(entry.get("status") or "done"),
                    input_json=dict(entry.get("inputs_summary") or {}),
                    output_json=dict(entry.get("outputs_summary") or {}),
                    evidence_json=list(entry.get("evidence_refs") or []),
                    error_message=str(entry.get("detail") or ""),
                    started_at=get_datetime_utc(),
                    finished_at=get_datetime_utc(),
                )
            )

    def _update_task_from_result(
        self,
        task_row: GwyPositionAnalysisTask,
        result: dict[str, Any],
    ) -> None:
        task_row.status = str(result.get("status") or "completed")
        task_row.stage = str(result.get("stage") or "persist_result")
        task_row.report_text = str(result.get("report") or "")
        task_row.trace_json = list(result.get("trace") or [])
        task_row.output_json = dict(result.get("output_json") or {})
        task_row.finished_at = get_datetime_utc()
        task_row.error_message = None
        archive_path = self._write_report_archive(task_row, result)
        if archive_path:
            task_row.output_json = {
                **dict(task_row.output_json or {}),
                "artifacts": {
                    **dict((task_row.output_json or {}).get("artifacts") or {}),
                    "report_markdown_path": archive_path,
                },
            }

    def _write_report_archive(
        self,
        task_row: GwyPositionAnalysisTask,
        result: dict[str, Any],
    ) -> str | None:
        report_text = str(result.get("report") or task_row.report_text or "").strip()
        if not report_text:
            return None

        archive_dir = (
            Path(__file__).resolve().parents[4]
            / "data"
            / "gwy_analysis_reports"
        )
        archive_dir.mkdir(parents=True, exist_ok=True)

        archive_path = archive_dir / f"{task_row.id}.md"
        title = str(
            dict(result.get("snapshot") or {}).get("title")
            or task_row.input_json.get("snapshot", {}).get("title")
            or "岗位分析报告"
        ).strip()
        created_at = getattr(task_row, "finished_at", None) or get_datetime_utc()
        metadata_lines = [
            f"# {title}",
            "",
            f"- task_id: {task_row.id}",
            f"- snapshot_id: {task_row.snapshot_id}",
            f"- generated_at: {created_at.isoformat()}",
            "",
        ]
        archive_path.write_text(
            "\n".join(metadata_lines) + report_text,
            encoding="utf-8",
        )
        return str(archive_path)

    def _push_report_to_feishu_legacy(
        self,
        task_row: GwyPositionAnalysisTask,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.feishu_push_agent is None:
            return None

        snapshot_data = dict(result.get("snapshot") or {})
        report_title = str(
            snapshot_data.get("title")
            or task_row.input_json.get("snapshot", {}).get("title")
            or "宀椾綅鍒嗘瀽鎶ュ憡"
        )
        push_result = self.feishu_push_agent.run(
            report_kind="analysis",
            title=report_title,
            report_text=str(result.get("report") or task_row.report_text or ""),
            task_id=str(task_row.id),
        )
        feishu_payload = self._serialize_feishu_push_result(push_result)
        task_row.output_json = {
            **dict(task_row.output_json or {}),
            "feishu_push": feishu_payload,
        }
        task_row.trace_json = [
            *list(task_row.trace_json or []),
            {
                "step": "feishu_push",
                "status": str(push_result.get("status") or "unknown"),
                "error_message": push_result.get("error_message"),
            },
        ]
        return feishu_payload

    def _serialize_snapshot(
        self,
        snapshot_row: GwyPositionAnalysisSnapshot,
    ) -> dict[str, Any]:
        return {
            "id": str(snapshot_row.id),
            "user_id": str(snapshot_row.user_id),
            "title": snapshot_row.title,
            "source_sheet": snapshot_row.source_sheet,
            "filters_json": dict(snapshot_row.filters_json or {}),
            "snapshot_json": dict(snapshot_row.snapshot_json or {}),
            "selected_position_ids": list(snapshot_row.selected_position_ids or []),
            "visible_columns": list(snapshot_row.visible_columns or []),
            "notes": snapshot_row.notes,
            "created_at": self._format_datetime(snapshot_row.created_at),
        }

    def _serialize_task(
        self,
        task_row: GwyPositionAnalysisTask,
    ) -> dict[str, Any]:
        return {
            "id": str(task_row.id),
            "snapshot_id": str(task_row.snapshot_id),
            "user_id": str(task_row.user_id),
            "status": task_row.status,
            "stage": task_row.stage,
            "input_json": dict(task_row.input_json or {}),
            "output_json": dict(task_row.output_json or {}),
            "report_text": task_row.report_text,
            "trace_json": list(task_row.trace_json or []),
            "error_message": task_row.error_message,
            "started_at": self._format_datetime(task_row.started_at),
            "finished_at": self._format_datetime(task_row.finished_at),
            "created_at": self._format_datetime(task_row.created_at),
        }

    def _serialize_feishu_push_result(
        self,
        push_result: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status": str(push_result.get("status") or "unknown"),
            "error_message": push_result.get("error_message"),
            "response_json": dict(push_result.get("response_json") or {}),
            "trace": list(push_result.get("trace") or []),
        }

    def _push_report_to_feishu(
        self,
        task_row: GwyPositionAnalysisTask,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.feishu_push_agent is None:
            return None

        webhook_url = self._resolve_feishu_webhook_url(task_row.user_id)
        if not webhook_url:
            feishu_payload = {
                "status": "skipped",
                "error_message": "Feishu webhook is not configured for this user.",
                "response_json": {},
                "trace": [
                    {
                        "step": "plan",
                        "status": "skipped",
                        "reason": "webhook_missing",
                    },
                    {
                        "step": "push",
                        "status": "skipped",
                        "reason": "webhook_missing",
                    },
                    {
                        "step": "reflect",
                        "status": "skipped",
                        "has_response": False,
                    },
                ],
            }
            task_row.output_json = {
                **dict(task_row.output_json or {}),
                "feishu_push": feishu_payload,
            }
            task_row.trace_json = [
                *list(task_row.trace_json or []),
                {
                    "step": "feishu_push",
                    "status": "skipped",
                    "error_message": "Feishu webhook is not configured for this user.",
                },
            ]
            return feishu_payload

        snapshot_data = dict(result.get("snapshot") or {})
        input_snapshot = dict(task_row.input_json.get("snapshot") or {})
        report_title = str(
            snapshot_data.get("title")
            or input_snapshot.get("title")
            or "岗位分析报告"
        )
        push_result = self.feishu_push_agent.run(
            report_kind="analysis",
            title=report_title,
            report_text=str(result.get("report") or task_row.report_text or ""),
            task_id=str(task_row.id),
            webhook_url=webhook_url,
            report_url=self._build_analysis_report_url(task_row.id),
        )
        feishu_payload = self._serialize_feishu_push_result(push_result)
        task_row.output_json = {
            **dict(task_row.output_json or {}),
            "feishu_push": feishu_payload,
        }
        task_row.trace_json = [
            *list(task_row.trace_json or []),
            {
                "step": "feishu_push",
                "status": str(push_result.get("status") or "unknown"),
                "error_message": push_result.get("error_message"),
            },
        ]
        return feishu_payload

    def _resolve_feishu_webhook_url(self, user_id: UUID) -> str | None:
        profile = self.session.exec(
            select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        ).first()
        webhook_url = str(profile.feishu_webhook_url or "").strip() if profile else ""
        if not webhook_url:
            webhook_url = str(getattr(settings, "FEISHU_WEBHOOK_URL", "") or "").strip()
        return webhook_url or None

    def _build_analysis_report_url(self, task_id: UUID) -> str | None:
        frontend_host = str(getattr(settings, "FRONTEND_HOST", "") or "").strip()
        if not frontend_host:
            return None
        return f"{frontend_host.rstrip('/')}/gwy/analysis?task_id={task_id}"

    def _load_user_profile(self, user_id: UUID) -> dict[str, Any]:
        profile_row = self.session.exec(
            select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        ).first()
        if profile_row is None:
            return {}

        profile = build_profile_summary(profile_row)
        profile["id"] = str(profile_row.id)
        profile["user_id"] = str(profile_row.user_id)
        return profile

    def _extract_exam_year(
        self,
        *,
        recommendation_context: dict[str, Any],
        user_profile: dict[str, Any],
    ) -> int | None:
        for candidate in (
            recommendation_context.get("year"),
            user_profile.get("exam_year"),
            user_profile.get("target_year"),
        ):
            if candidate in (None, ""):
                continue
            try:
                return int(candidate)
            except (TypeError, ValueError):
                continue
        return None

    def _extract_exam_type(self, recommendation_context: dict[str, Any]) -> str:
        exam_type = str(recommendation_context.get("exam_type") or "").strip()
        return exam_type or "national"

    def _extract_study_hours(self, user_profile: dict[str, Any]) -> int:
        candidate = user_profile.get("daily_study_hours")
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            value = 4
        return max(1, value)

    def _format_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
