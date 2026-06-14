from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlmodel import Session

from app.core.config import settings
from app.gwy.models import GwyPosition
from app.gwy.skills.position_recommendation_skills import (
    PositionRecommendationCriteria,
    _major_requirement_search_terms,
    build_position_brief,
    build_recommendation_summary,
    extract_position_recommendation_criteria,
    position_passes_hard_filters,
    position_to_dict,
    score_position,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PositionListFilters:
    year: int = 2026
    major: str | None = None
    education: str | None = None
    degree: str | None = None
    political_status: str | None = None
    region: str | None = None
    department: str | None = None
    job_title: str | None = None
    page: int = 1
    page_size: int = 20


class PositionCatalogService:
    def __init__(self, session: Session, redis_client: Any | None = None) -> None:
        self.session = session
        self.redis_client = redis_client or self._build_redis_client()

    def get_page_state(self, user_id: UUID | str) -> dict[str, Any] | None:
        if self.redis_client is None:
            return None
        cache_key = self._build_page_state_key(user_id)
        try:
            raw = self.redis_client.get(cache_key)
        except Exception:  # pragma: no cover - best effort cache
            logger.debug(
                "Failed to read Gwy position page state from Redis.",
                exc_info=True,
            )
            return None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug(
                "Failed to decode Gwy position page state payload.",
                exc_info=True,
            )
            return None
        if not isinstance(payload, dict):
            return None
        logger.info(
            "Gwy position page state cache hit | user_id=%s keys=%s",
            user_id,
            list(payload.keys()),
        )
        return payload

    def save_page_state(self, user_id: UUID | str, state: dict[str, Any]) -> bool:
        if self.redis_client is None:
            return False
        cache_key = self._build_page_state_key(user_id)
        try:
            self.redis_client.set(
                cache_key,
                json.dumps(state, ensure_ascii=False),
            )
            logger.info(
                "Gwy position page state cached | user_id=%s sheets=%s",
                user_id,
                len((state.get("sheets") or {}) if isinstance(state, dict) else {}),
            )
            return True
        except Exception:  # pragma: no cover - best effort cache
            logger.debug(
                "Failed to write Gwy position page state to Redis.",
                exc_info=True,
            )
            return False

    def clear_page_state(self, user_id: UUID | str) -> bool:
        if self.redis_client is None:
            return False
        cache_key = self._build_page_state_key(user_id)
        try:
            deleted = int(self.redis_client.delete(cache_key))
            logger.info(
                "Gwy position page state cache cleared | user_id=%s deleted=%s",
                user_id,
                deleted,
            )
            return deleted > 0
        except Exception:  # pragma: no cover - best effort cache
            logger.debug(
                "Failed to clear Gwy position page state from Redis.",
                exc_info=True,
            )
            return False

    def clear_cache(self) -> int:
        if self.redis_client is None:
            return 0

        try:
            keys = list(self.redis_client.scan_iter("gwy:position_catalog:*"))
            if not keys:
                return 0
            deleted = int(self.redis_client.delete(*keys))
            logger.info("Gwy position catalog cache cleared | deleted=%s", deleted)
            return deleted
        except Exception:  # pragma: no cover - best effort cache invalidation
            logger.warning(
                "Failed to clear Gwy position catalog cache.",
                exc_info=True,
            )
            return 0

    def list_positions(self, filters: PositionListFilters) -> dict[str, Any]:
        normalized_page = max(1, filters.page)
        normalized_page_size = min(max(1, filters.page_size), 100)
        return self._query_positions(
            filters=filters,
            page=normalized_page,
            page_size=normalized_page_size,
            include_all=False,
        )

    def list_positions_grid(self, filters: PositionListFilters) -> dict[str, Any]:
        return self._query_positions(
            filters=filters,
            page=1,
            page_size=0,
            include_all=True,
        )

    def analyze_positions(
        self,
        *,
        position_ids: list[UUID],
        query: str,
        profile: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        if not position_ids:
            return {
                "analysis": "当前没有可分析的岗位，请先在表格中勾选至少一条岗位。",
                "summary": {},
                "recommendations": [],
                "selected_positions": [],
                "retrieval_trace": [
                    {"step": "position_analysis", "selected_count": 0}
                ],
            }

        statement = select(GwyPosition).where(GwyPosition.id.in_(position_ids))
        selected_positions = list(self.session.exec(statement).scalars().all())
        criteria = extract_position_recommendation_criteria(query, profile or {})

        scored_records: list[dict[str, Any]] = []
        exact_matches: list[dict[str, Any]] = []
        relaxed_matches: list[dict[str, Any]] = []

        for position in selected_positions:
            matched, hard_reasons, hard_risks = position_passes_hard_filters(
                position,
                criteria,
            )
            scored = score_position(position, criteria)
            position_dict = position_to_dict(position)
            record = {
                **position_dict,
                **scored,
                "hard_filter_passed": matched,
                "hard_filter_reasons": hard_reasons,
                "hard_filter_risks": hard_risks,
            }
            scored_records.append(record)
            if matched:
                exact_matches.append(record)
            else:
                relaxed_matches.append(record)

        ranked_source = exact_matches if exact_matches else relaxed_matches
        ranked_source.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        recommendations = [
            build_position_brief(
                item,
                {
                    "score": item.get("score", 0.0),
                    "recommend_level": item.get("recommend_level", "weak_match"),
                    "risk_level": item.get("risk_level", "high"),
                    "need_manual_confirm": item.get("need_manual_confirm", True),
                    "reasons": list(item.get("reasons") or []),
                    "risks": list(item.get("risks") or []),
                },
            )
            for item in ranked_source[:top_k]
        ]
        summary = build_recommendation_summary(
            criteria,
            recommendations,
            candidate_count=len(selected_positions),
            filtered_count=len(exact_matches),
        )
        analysis = self._build_analysis_text(
            criteria=criteria,
            recommendations=recommendations,
            selected_count=len(selected_positions),
            exact_count=len(exact_matches),
        )
        trace = [
            {
                "step": "position_analysis",
                "selected_count": len(selected_positions),
                "exact_match_count": len(exact_matches),
                "relaxed_match_count": len(relaxed_matches),
                "query": query,
                "top_k": top_k,
            }
        ]
        return {
            "analysis": analysis,
            "summary": summary,
            "recommendations": recommendations,
            "selected_positions": scored_records,
            "retrieval_trace": trace,
        }

    def get_position_history(
        self,
        position: dict[str, Any] | GwyPosition,
        *,
        limit: int = 5,
    ) -> dict[str, Any]:
        position_dict = (
            position_to_dict(position) if isinstance(position, GwyPosition) else dict(position)
        )
        position_id = str(position_dict.get("id") or "").strip()
        position_code = str(position_dict.get("position_code") or "").strip()
        department_code = str(position_dict.get("department_code") or "").strip()
        department_name = str(position_dict.get("department_name") or "").strip()
        office_name = str(position_dict.get("office_name") or "").strip()
        job_title = str(position_dict.get("job_title") or "").strip()

        candidate_statements: list[tuple[str, Any]] = []
        if position_code:
            candidate_statements.append(
                (
                    "position_code",
                    select(GwyPosition).where(GwyPosition.position_code == position_code),
                )
            )
        if department_code and job_title:
            candidate_statements.append(
                (
                    "department_code_job_title",
                    select(GwyPosition).where(
                        GwyPosition.department_code == department_code,
                        GwyPosition.job_title == job_title,
                    ),
                )
            )
        if department_name and office_name and job_title:
            candidate_statements.append(
                (
                    "department_name_office_job_title",
                    select(GwyPosition).where(
                        GwyPosition.department_name == department_name,
                        GwyPosition.office_name == office_name,
                        GwyPosition.job_title == job_title,
                    ),
                )
            )
        if department_name and job_title:
            candidate_statements.append(
                (
                    "department_name_job_title",
                    select(GwyPosition).where(
                        GwyPosition.department_name == department_name,
                        GwyPosition.job_title == job_title,
                    ),
                )
            )
        if department_name:
            candidate_statements.append(
                (
                    "department_name",
                    select(GwyPosition).where(GwyPosition.department_name == department_name),
                )
            )

        if not candidate_statements:
            return {
                "match_basis": "none",
                "records": [],
                "summary": {
                    "record_count": 0,
                    "history_years": [],
                    "recruit_count_trend": "unknown",
                    "interview_ratio_trend": "unknown",
                    "latest_recruit_count": None,
                    "latest_interview_ratio": None,
                },
            }

        if position_id:
            try:
                excluded_position_id = UUID(position_id)
            except Exception:
                excluded_position_id = None
        else:
            excluded_position_id = None

        collected_rows: dict[UUID, GwyPosition] = {}
        used_bases: list[str] = []
        for basis, statement in candidate_statements:
            if excluded_position_id is not None:
                statement = statement.where(GwyPosition.id != excluded_position_id)
            rows = list(self.session.exec(statement).scalars().all())
            if rows:
                used_bases.append(basis)
            for row in rows:
                collected_rows[row.id] = row
            if len(collected_rows) >= limit:
                break

        rows = list(collected_rows.values())
        rows = sorted(
            rows,
            key=lambda row: (
                _extract_year_from_source_file(row.source_file) or 0,
                row.source_row_number or 0,
            ),
            reverse=True,
        )[:limit]
        records = [self._serialize_history_row(row) for row in rows]
        summary = _summarize_history_records(records)
        summary["match_basis"] = used_bases[0] if used_bases else "department_name"
        summary["match_candidates"] = used_bases
        summary["history_years"] = [
            int(item["year"]) for item in records if item.get("year") is not None
        ]
        return {
            "match_basis": summary["match_basis"],
            "records": records,
            "summary": summary,
        }

    def _build_filters(self, filters: PositionListFilters) -> list[Any]:
        conditions: list[Any] = []
        if filters.year:
            conditions.append(
                or_(
                    GwyPosition.source_file.contains(str(filters.year)),
                    GwyPosition.source_file.contains(f"{filters.year}年度"),
                )
            )
        if filters.major:
            major_terms = _major_requirement_search_terms(filters.major)
            major_clauses = [
                GwyPosition.major_requirement.is_(None),
                GwyPosition.major_requirement == "",
                GwyPosition.major_requirement.contains(filters.major),
                *[
                    GwyPosition.major_requirement.contains(term)
                    for term in major_terms
                    if term and term != filters.major
                ],
                GwyPosition.major_requirement.contains("不限"),
                GwyPosition.major_requirement.contains("不限制"),
            ]
            conditions.append(or_(*major_clauses))
        if filters.education:
            conditions.append(
                or_(
                    GwyPosition.education_requirement.is_(None),
                    GwyPosition.education_requirement == "",
                    GwyPosition.education_requirement.contains(filters.education),
                    GwyPosition.education_requirement.contains("不限"),
                    GwyPosition.education_requirement.contains("不限制"),
                )
            )
        if filters.degree:
            conditions.append(
                or_(
                    GwyPosition.degree_requirement.is_(None),
                    GwyPosition.degree_requirement == "",
                    GwyPosition.degree_requirement.contains(filters.degree),
                    GwyPosition.degree_requirement.contains("相对应"),
                    GwyPosition.degree_requirement.contains("最高学历"),
                    GwyPosition.degree_requirement.contains("对应学位"),
                    GwyPosition.degree_requirement.contains("不限"),
                    GwyPosition.degree_requirement.contains("不限制"),
                )
            )
        if filters.political_status:
            conditions.append(
                or_(
                    GwyPosition.political_status_requirement.is_(None),
                    GwyPosition.political_status_requirement == "",
                    GwyPosition.political_status_requirement.contains(
                        filters.political_status
                    ),
                    GwyPosition.political_status_requirement.contains("不限"),
                    GwyPosition.political_status_requirement.contains("不限制"),
                )
            )
        if filters.region:
            region = filters.region
            conditions.append(
                or_(
                    GwyPosition.work_location.contains(region),
                    GwyPosition.household_registration_location.contains(region),
                    GwyPosition.position_distribution.contains(region),
                )
            )
        if filters.department:
            department = filters.department
            conditions.append(
                or_(
                    GwyPosition.department_name.contains(department),
                    GwyPosition.office_name.contains(department),
                )
            )
        if filters.job_title:
            job_title = filters.job_title
            conditions.append(
                or_(
                    GwyPosition.job_title.contains(job_title),
                    GwyPosition.position_desc.contains(job_title),
                )
            )
        return conditions

    def _serialize_position(self, position: GwyPosition) -> dict[str, Any]:
        data = position_to_dict(position)
        return {
            "id": data["id"],
            "department_code": data["department_code"],
            "department_name": data["department_name"],
            "office_name": data["office_name"],
            "institution_type": data["institution_type"],
            "job_title": data["job_title"],
            "position_attribute": data["position_attribute"],
            "position_distribution": data["position_distribution"],
            "position_desc": data["position_desc"],
            "position_code": data["position_code"],
            "institution_level": data["institution_level"],
            "exam_category": data["exam_category"],
            "recruit_count": data["recruit_count"],
            "major_requirement": data["major_requirement"],
            "education_requirement": data["education_requirement"],
            "degree_requirement": data["degree_requirement"],
            "political_status_requirement": data["political_status_requirement"],
            "grassroots_years_requirement": data["grassroots_years_requirement"],
            "grassroots_project_experience": data["grassroots_project_experience"],
            "professional_test_in_interview": data["professional_test_in_interview"],
            "interview_ratio": data["interview_ratio"],
            "work_location": data["work_location"],
            "household_registration_location": data["household_registration_location"],
            "remarks": data["remarks"],
            "department_website": data["department_website"],
            "contact_phone_1": data["contact_phone_1"],
            "contact_phone_2": data["contact_phone_2"],
            "contact_phone_3": data["contact_phone_3"],
            "source_file": data["source_file"],
            "source_sheet": data["source_sheet"],
            "source_row_number": data["source_row_number"],
            "raw_data": data["raw_data"],
        }

    def _serialize_filters(self, filters: PositionListFilters) -> dict[str, Any]:
        return {
            "year": filters.year,
            "major": filters.major,
            "education": filters.education,
            "degree": filters.degree,
            "political_status": filters.political_status,
            "region": filters.region,
            "department": filters.department,
            "job_title": filters.job_title,
        }

    def _query_positions(
        self,
        *,
        filters: PositionListFilters,
        page: int,
        page_size: int,
        include_all: bool,
    ) -> dict[str, Any]:
        cache_key = self._build_cache_key(filters, include_all=include_all)
        logger.info(
            "Gwy position catalog query start | include_all=%s page=%s page_size=%s filters=%s cache_key=%s",
            include_all,
            page,
            page_size,
            self._serialize_filters(filters),
            cache_key,
        )
        if self.redis_client is not None:
            cached = self._read_cache(cache_key)
            if cached is not None:
                logger.info(
                    "Gwy position catalog cache hit | cache_key=%s count=%s data_len=%s",
                    cache_key,
                    cached.get("count"),
                    len(cached.get("data") or []),
                )
                return cached
            logger.info(
                "Gwy position catalog cache miss | cache_key=%s",
                cache_key,
            )

        statement = select(GwyPosition)
        conditions = self._build_filters(filters)
        if conditions:
            statement = statement.where(*conditions)

        count_statement = select(func.count()).select_from(GwyPosition)
        if conditions:
            count_statement = count_statement.where(*conditions)

        total = int(self.session.exec(count_statement).one()[0])
        ordered_statement = statement.order_by(
            GwyPosition.source_row_number.asc(), GwyPosition.created_at.asc()
        )

        if include_all:
            rows = list(self.session.exec(ordered_statement).scalars().all())
            response_page_size = total
        else:
            rows = list(
                self.session.exec(
                    ordered_statement.offset((page - 1) * page_size).limit(page_size)
                ).scalars().all()
            )
            response_page_size = page_size

        payload = {
            "data": [self._serialize_position(row) for row in rows],
            "count": total,
            "page": page,
            "page_size": response_page_size,
            "filters": self._serialize_filters(filters),
        }
        logger.info(
            "Gwy position catalog db result | total=%s returned=%s include_all=%s cache_key=%s",
            total,
            len(rows),
            include_all,
            cache_key,
        )
        if self.redis_client is not None:
            self._write_cache(cache_key, payload)
        return payload

    def _build_cache_key(
        self,
        filters: PositionListFilters,
        *,
        include_all: bool,
    ) -> str:
        payload = {
            "year": filters.year,
            "major": filters.major,
            "education": filters.education,
            "degree": filters.degree,
            "political_status": filters.political_status,
            "region": filters.region,
            "department": filters.department,
            "job_title": filters.job_title,
            "include_all": include_all,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return f"gwy:position_catalog:{digest}"

    def _build_page_state_key(self, user_id: UUID | str) -> str:
        return f"gwy:position_page_state:{user_id}"

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        if self.redis_client is None:
            return None
        try:
            raw = self.redis_client.get(cache_key)
        except Exception:  # pragma: no cover - best effort cache
            logger.debug("Failed to read position cache from Redis.", exc_info=True)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Failed to decode position cache payload.", exc_info=True)
            return None

    def _write_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        if self.redis_client is None:
            return
        try:
            self.redis_client.set(
                cache_key,
                json.dumps(payload, ensure_ascii=False),
            )
            logger.info(
                "Gwy position catalog cache stored | cache_key=%s rows=%s",
                cache_key,
                len(payload.get("data") or []),
            )
        except Exception:  # pragma: no cover - best effort cache
            logger.debug("Failed to write position cache to Redis.", exc_info=True)

    def _serialize_history_row(self, position: GwyPosition) -> dict[str, Any]:
        data = self._serialize_position(position)
        data["year"] = _extract_year_from_source_file(str(data.get("source_file") or ""))
        return data

    def _build_redis_client(self) -> Any | None:
        if not settings.REDIS_URL:
            return None
        try:
            import redis

            client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
            client.ping()
            return client
        except Exception:  # pragma: no cover - Redis best effort
            logger.debug(
                "Redis unavailable for position catalog cache.",
                exc_info=True,
            )
            return None

    def _build_analysis_text(
        self,
        *,
        criteria: PositionRecommendationCriteria,
        recommendations: list[dict[str, Any]],
        selected_count: int,
        exact_count: int,
    ) -> str:
        lines = [
            f"已分析 {selected_count} 条已选岗位，其中 {exact_count} 条满足当前硬性条件。",
        ]
        if criteria.major:
            lines.append(f"专业偏好：{criteria.major}")
        if criteria.education:
            lines.append(f"学历要求：{criteria.education}")
        if criteria.degree:
            lines.append(f"学位要求：{criteria.degree}")
        if criteria.political_status:
            lines.append(f"政治面貌：{criteria.political_status}")
        if recommendations:
            top = recommendations[0]
            lines.append(
                "当前最值得优先关注的是 "
                f"{top.get('department_name') or ''}"
                f"{top.get('office_name') or ''}"
                f"{top.get('job_title') or ''}，"
                f"匹配度约 {top.get('score', 0)} 分。"
            )
        else:
            lines.append("当前已选岗位里没有明显高匹配项，建议继续缩小筛选条件。")
        return "".join(lines)


def _extract_year_from_source_file(source_file: str) -> int | None:
    match = re.search(r"(20\d{2})", source_file or "")
    if not match:
        return None
    return int(match.group(1))


def _summarize_history_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    recruit_counts = [
        value
        for value in (_safe_int(record.get("recruit_count")) for record in records)
        if value is not None
    ]
    interview_ratios = [
        value
        for value in (
            _parse_ratio_value(str(record.get("interview_ratio") or ""))
            for record in records
        )
        if value is not None
    ]
    latest_recruit = recruit_counts[0] if recruit_counts else None
    earliest_recruit = recruit_counts[-1] if recruit_counts else None
    latest_ratio = interview_ratios[0] if interview_ratios else None
    earliest_ratio = interview_ratios[-1] if interview_ratios else None
    return {
        "record_count": len(records),
        "latest_recruit_count": latest_recruit,
        "earliest_recruit_count": earliest_recruit,
        "recruit_count_delta": (
            None
            if latest_recruit is None or earliest_recruit is None
            else latest_recruit - earliest_recruit
        ),
        "recruit_count_trend": _trend_label(recruit_counts),
        "latest_interview_ratio": latest_ratio,
        "earliest_interview_ratio": earliest_ratio,
        "interview_ratio_trend": _trend_label(interview_ratios),
    }


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(str(value).strip()))
    except Exception:
        return None


def _parse_ratio_value(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)", text)
    if match:
        left = float(match.group(1))
        right = float(match.group(2))
        if right == 0:
            return None
        return left / right
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1)) / 100.0
    return None


def _trend_label(values: list[float]) -> str:
    if len(values) < 2:
        return "insufficient_data"
    first = values[0]
    last = values[-1]
    if abs(first - last) < 1e-6:
        return "stable"
    return "downward" if first > last else "upward"
