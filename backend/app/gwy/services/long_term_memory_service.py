"""Long-term memory persistence and retrieval across sessions.

- Record position decisions (like/dislike/view)
- Agent experience learning (success/failure patterns)
- Cross-session user profile enrichment
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.gwy.models import (
    GwyDecisionMemory,
    GwyExperienceMemory,
    GwyRecommendationTask,
    GwyUserProfile,
)

logger = logging.getLogger(__name__)
_LONG_TERM_CACHE_TTL_SECONDS = 24 * 60 * 60


def _looks_like_invalid_identity_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    normalized = re.sub(r"[。！？?!,，；;:：]+$", "", text)
    if not normalized:
        return True
    if len(normalized) > 16:
        return True
    if re.search(r"\s", normalized):
        return True
    if any(
        token in normalized
        for token in (
            "什么",
            "谁",
            "哪",
            "多少",
            "怎么",
            "如何",
            "未知",
            "待定",
            "暂无",
            "占位",
            "null",
            "none",
            "N/A",
        )
    ):
        return True
    return False


class LongTermMemoryService:

    def __init__(self, *, session: Session, redis_client: Any | None = None) -> None:
        self.session = session
        self.redis = redis_client or self._build_redis_client()

    # -- Position decisions ------------------------------------------

    def record_position_decision(
        self,
        *,
        user_id: UUID,
        position_id: UUID | None = None,
        decision_type: str,
        decision_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GwyDecisionMemory:
        decision = GwyDecisionMemory(
            user_id=user_id,
            position_id=position_id,
            decision_type=decision_type,
            decision_reason=decision_reason,
            metadata_json=dict(metadata or {}),
        )
        self.session.add(decision)
        self.session.commit()
        self.session.refresh(decision)
        return decision

    def get_position_decisions(
        self, *, user_id: UUID, decision_type: str | None = None, limit: int = 20
    ) -> list[GwyDecisionMemory]:
        stmt = select(GwyDecisionMemory).where(
            GwyDecisionMemory.user_id == user_id
        ).order_by(GwyDecisionMemory.created_at.desc())
        if decision_type:
            stmt = stmt.where(GwyDecisionMemory.decision_type == decision_type)
        return list(self.session.exec(stmt.limit(limit)).all())

    def _ordered_user_profile(self, profile: GwyUserProfile | None) -> dict[str, Any]:
        if profile is None:
            return {}
        return {
            "name": profile.name if not _looks_like_invalid_identity_value(profile.name) else None,
            "nickname": profile.nickname if not _looks_like_invalid_identity_value(profile.nickname) else None,
            "political_status": profile.political_status,
            "major": profile.major,
            "education": profile.education,
            "degree": profile.degree,
            "is_fresh_graduate": profile.is_fresh_graduate,
            "grassroots_experience_years": profile.grassroots_experience_years,
            "target_regions": list(profile.target_regions or []),
            "desired_departments": list(profile.desired_departments or []),
            "desired_positions": list(profile.desired_positions or []),
            "avoid_conditions": list(profile.avoid_conditions or []),
            "excluded_positions": list(profile.excluded_positions or []),
            "daily_study_hours": profile.daily_study_hours,
            "notes": profile.notes,
        }

    # -- Agent experience learning ----------------------------------

    def record_agent_experience(
        self,
        *,
        agent_name: str,
        scenario: str,
        trigger: str,
        lesson: str | None = None,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> GwyExperienceMemory:
        stmt = select(GwyExperienceMemory).where(
            GwyExperienceMemory.agent_name == agent_name,
            GwyExperienceMemory.scenario == scenario,
            GwyExperienceMemory.trigger == trigger,
        )
        existing = self.session.exec(stmt).first()
        if existing:
            if success:
                existing.success_count += 1
            existing.lesson = lesson
            existing.metadata_json = dict(metadata or {})
            self.session.add(existing)
            self.session.commit()
            return existing

        exp = GwyExperienceMemory(
            agent_name=agent_name,
            scenario=scenario,
            trigger=trigger,
            lesson=lesson,
            success_count=1 if success else 0,
            metadata_json=dict(metadata or {}),
        )
        self.session.add(exp)
        self.session.commit()
        self.session.refresh(exp)
        return exp

    def get_relevant_experiences(
        self, *, agent_name: str | None = None, scenario: str | None = None, limit: int = 10
    ) -> list[GwyExperienceMemory]:
        stmt = select(GwyExperienceMemory).order_by(
            GwyExperienceMemory.success_count.desc()
        )
        if agent_name:
            stmt = stmt.where(GwyExperienceMemory.agent_name == agent_name)
        if scenario:
            stmt = stmt.where(GwyExperienceMemory.scenario == scenario)
        return list(self.session.exec(stmt.limit(limit)).all())

    # -- User profile enrichment ------------------------------------

    def auto_enrich_user_profile(
        self,
        *,
        user_id: UUID,
        extracted_fields: dict[str, Any],
    ) -> dict[str, Any]:
        pending_updates: dict[str, Any] = {}
        profile_stmt = select(GwyUserProfile).where(
            GwyUserProfile.user_id == user_id
        )
        profile = self.session.exec(profile_stmt).first()
        field_mapping = {
            "name": "name",
            "nickname": "nickname",
            "target_regions": "target_regions",
            "desired_departments": "desired_departments",
            "degree": "degree",
            "major": "major",
            "education": "education",
            "political_status": "political_status",
        }
        for src_field, dst_field in field_mapping.items():
            value = extracted_fields.get(src_field)
            if value is None:
                continue
            if dst_field in {"name", "nickname"} and _looks_like_invalid_identity_value(value):
                continue
            pending_updates[dst_field] = value

        if not pending_updates:
            return {}

        if profile is None:
            profile = GwyUserProfile(user_id=user_id)
            self.session.add(profile)
            self.session.flush()

        updated: dict[str, Any] = {}
        list_fields = {"target_regions", "desired_departments", "desired_positions"}
        for dst_field, value in pending_updates.items():
            current = getattr(profile, dst_field, None)
            if dst_field in list_fields:
                existing = list(current or []) if isinstance(current, list) else []
                values = value if isinstance(value, list) else [value]
                changed = False
                for item in values:
                    if not item or item in existing:
                        continue
                    existing.append(item)
                    changed = True
                if changed or current is None:
                    setattr(profile, dst_field, existing)
                    updated[dst_field] = existing
                continue
            if current and isinstance(current, list) and isinstance(value, str):
                if value not in current:
                    current.append(value)
                    setattr(profile, dst_field, current)
                    updated[dst_field] = current
            elif value and current != value:
                setattr(profile, dst_field, value)
                updated[dst_field] = value

        if updated:
            self.session.add(profile)
            self.session.commit()
            self._invalidate_user_cache(user_id)
            logger.info("Enriched user profile for user_id=%s: %s", user_id, list(updated.keys()))

        return updated

    # -- Cross-session summary --------------------------------------

    def build_cross_session_summary(self, *, user_id: UUID) -> dict[str, Any]:
        cached_summary = self._load_cached_summary(user_id)
        if cached_summary is not None:
            return cached_summary

        decisions = self.get_position_decisions(user_id=user_id)
        liked_departments: list[str] = []
        liked_jobs: list[str] = []
        for d in decisions:
            meta = d.metadata_json or {}
            dept = meta.get("department_name", "")
            job = meta.get("job_title", "")
            if d.decision_type == "like":
                if dept:
                    liked_departments.append(dept)
                if job:
                    liked_jobs.append(job)

        tasks = self.session.exec(
            select(GwyRecommendationTask)
            .where(GwyRecommendationTask.user_id == user_id)
            .order_by(GwyRecommendationTask.created_at.desc())
            .limit(10)
        ).all()

        profile_stmt = select(GwyUserProfile).where(
            GwyUserProfile.user_id == user_id
        )
        profile = self.session.exec(profile_stmt).first()
        user_profile = self._ordered_user_profile(profile)

        summary = {
            "total_analyses": len(tasks),
            "total_decisions": len(decisions),
            "liked_departments": list(set(liked_departments))[:10],
            "liked_job_titles": list(set(liked_jobs))[:10],
            "last_analysis_at": str(tasks[0].created_at) if tasks else None,
            "user_profile": user_profile,
        }
        self._store_cached_summary(user_id, summary)
        return summary

    def build_user_profile_context(self, *, user_id: UUID) -> dict[str, Any]:
        profile_stmt = select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        profile = self.session.exec(profile_stmt).first()
        return self._ordered_user_profile(profile)

    def _build_redis_client(self) -> Any | None:
        try:
            from app.core.config import settings

            if not settings.REDIS_URL:
                return None
            import redis

            client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
            client.ping()
            return client
        except Exception:  # pragma: no cover - Redis best-effort
            logger.debug("Redis unavailable for long-term memory cache.", exc_info=True)
            return None

    def _summary_cache_key(self, user_id: UUID) -> str:
        return f"gwy:ltm:summary:{user_id}"

    def _profile_cache_key(self, user_id: UUID) -> str:
        return f"gwy:ltm:profile:{user_id}"

    def _invalidate_user_cache(self, user_id: UUID) -> None:
        if self.redis is None:
            return
        try:
            self.redis.delete(self._summary_cache_key(user_id), self._profile_cache_key(user_id))
        except Exception:  # pragma: no cover - Redis best-effort
            logger.debug("Failed to invalidate long-term memory cache.", exc_info=True)

    def _store_cached_summary(self, user_id: UUID, summary: dict[str, Any]) -> None:
        if self.redis is None:
            return
        try:
            self.redis.setex(
                self._summary_cache_key(user_id),
                _LONG_TERM_CACHE_TTL_SECONDS,
                json.dumps(summary, ensure_ascii=False),
            )
        except Exception:  # pragma: no cover - Redis best-effort
            logger.debug("Failed to store long-term summary cache.", exc_info=True)

    def _load_cached_summary(self, user_id: UUID) -> dict[str, Any] | None:
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(self._summary_cache_key(user_id))
            if not raw:
                return None
            return json.loads(raw)
        except Exception:  # pragma: no cover - Redis best-effort
            logger.debug("Failed to load long-term summary cache.", exc_info=True)
            return None
