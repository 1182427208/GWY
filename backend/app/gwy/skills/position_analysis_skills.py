from __future__ import annotations

import re
from typing import Any

from app.gwy.skills.position_recommendation_skills import build_profile_summary


def normalize_analysis_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(snapshot or {})
    nested_snapshot = dict(payload.get("snapshot_json") or {})

    filters_json = payload.get("filters_json")
    if not isinstance(filters_json, dict):
        filters_json = nested_snapshot.get("filters_json")
    normalized_filters = dict(filters_json or {})

    selected_position_ids = _normalize_string_list(
        payload.get("selected_position_ids") or nested_snapshot.get("selected_position_ids")
    )
    visible_columns = _normalize_string_list(
        payload.get("visible_columns") or nested_snapshot.get("visible_columns")
    )

    title = _clean_text(
        payload.get("title")
        or nested_snapshot.get("title")
        or "岗位分析快照"
    )
    source_sheet = _clean_text(
        payload.get("source_sheet") or nested_snapshot.get("source_sheet")
    )
    notes = _clean_text(payload.get("notes") or nested_snapshot.get("notes"))

    normalized = {
        "title": title,
        "source_sheet": source_sheet,
        "filters_json": normalized_filters,
        "snapshot_json": nested_snapshot or dict(payload),
        "selected_position_ids": selected_position_ids,
        "visible_columns": visible_columns,
        "notes": notes,
    }
    normalized["snapshot_json"].setdefault("title", title)
    if source_sheet:
        normalized["snapshot_json"].setdefault("source_sheet", source_sheet)
    normalized["snapshot_json"].setdefault("filters_json", normalized_filters)
    normalized["snapshot_json"].setdefault(
        "selected_position_ids", list(selected_position_ids)
    )
    normalized["snapshot_json"].setdefault("visible_columns", list(visible_columns))
    if notes:
        normalized["snapshot_json"].setdefault("notes", notes)
    return normalized


def build_analysis_scope(
    snapshot: dict[str, Any],
    *,
    profile: Any | None = None,
) -> dict[str, Any]:
    normalized = normalize_analysis_snapshot(snapshot)
    filters = dict(normalized.get("filters_json") or {})
    selected_position_ids = list(normalized.get("selected_position_ids") or [])
    visible_columns = list(normalized.get("visible_columns") or [])
    notes = str(normalized.get("notes") or "").strip()
    year = filters.get("year") or normalized.get("year") or 2026
    profile_summary = build_profile_summary(profile)
    effective_profile = _merge_analysis_profile(
        profile_summary=profile_summary,
        filters=filters,
        notes=notes,
    )

    title = _derive_report_title(str(normalized.get("title") or "岗位分析"))
    query_parts = [
        title,
        str(effective_profile.get("major") or ""),
        str(effective_profile.get("education") or ""),
        str(effective_profile.get("degree") or ""),
        " ".join(list(effective_profile.get("target_regions") or [])),
        " ".join(list(effective_profile.get("desired_departments") or [])),
        notes,
    ]
    query = " ".join(part for part in query_parts if part).strip()
    if not query:
        query = title

    evidence_queries = _build_evidence_queries(
        title=title,
        filters=effective_profile,
        notes=notes,
        visible_columns=visible_columns,
    )
    selected_count = len(selected_position_ids)
    summary_lines = [
        f"快照标题: {normalized.get('title') or '岗位分析快照'}",
        f"已选岗位: {selected_count}",
        f"分析年份: {year}",
    ]
    if filters:
        summary_lines.append(
            "筛选条件: "
            + "，".join(
                f"{key}={value}"
                for key, value in filters.items()
                if value not in (None, "", [], {})
            )
        )
    if notes:
        summary_lines.append(f"备注: {notes}")

    return {
        **normalized,
        "report_title": title,
        "year": year,
        "query": query,
        "evidence_queries": evidence_queries,
        "selected_count": selected_count,
        "summary_lines": summary_lines,
        "analysis_goal": "结合 PostgreSQL 岗位事实与 Milvus 政策证据，输出可追踪的岗位分析报告",
        "profile_summary": profile_summary,
        "effective_profile": effective_profile,
        "report_outline": render_analysis_outline(
            {
                "report_title": title,
                "selected_count": selected_count,
                "visible_columns": visible_columns,
                "filters_json": filters,
                "notes": notes,
            },
            [],
        ),
    }


def build_analysis_clarification(
    scope: dict[str, Any],
    *,
    profile: Any | None = None,
) -> dict[str, Any]:
    normalized = normalize_analysis_snapshot(scope)
    filters = dict(normalized.get("filters_json") or {})
    selected_count = len(normalized.get("selected_position_ids") or [])
    notes = str(normalized.get("notes") or "").strip()
    effective_profile = dict(
        scope.get("effective_profile")
        or build_profile_summary(profile)
        or {}
    )

    missing_fields: list[str] = []
    questions: list[str] = []

    if selected_count <= 0:
        missing_fields.append("selected_position_ids")
        questions.append(
            "请先至少选择 1 条岗位，或者直接告诉我你要重点分析的岗位代码或岗位名称。"
        )

    major = str(
        effective_profile.get("major")
        or filters.get("major")
        or ""
    ).strip()
    if not major:
        missing_fields.append("major")
        questions.append(
            "请补充你的专业，方便我判断岗位是否能报、风险在哪里。"
        )

    education = str(
        effective_profile.get("education")
        or filters.get("education")
        or ""
    ).strip()
    if not education:
        missing_fields.append("education")
        questions.append(
            "请补充学历信息，方便我判断岗位的学历门槛是否满足。"
        )

    degree = str(
        effective_profile.get("degree")
        or filters.get("degree")
        or ""
    ).strip()
    if not degree:
        missing_fields.append("degree")
        questions.append(
            "请补充学位信息，方便我判断是否存在学位限制。"
        )

    deduplicated_questions = _deduplicate_strings(questions)
    needs_more_info = bool(deduplicated_questions)
    if not needs_more_info and selected_count > 0:
        return {
            "needs_more_info": False,
            "missing_fields": [],
            "clarifying_questions": [],
            "clarification_reason": "",
        }

    reason_parts = [
        "当前快照里还缺少足够的报考约束信息，",
        "如果直接出最终报告，容易把岗位匹配和资格风险判断说得过满。",
    ]
    if selected_count <= 0:
        reason_parts.append("目前还没有明确选中的岗位。")
    if notes and major:
        reason_parts.append("当前快照已经足够生成完整报告。")
    return {
        "needs_more_info": needs_more_info,
        "missing_fields": _deduplicate_strings(missing_fields),
        "clarifying_questions": deduplicated_questions,
        "clarification_reason": "".join(reason_parts),
    }


def render_analysis_outline(
    scope: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[str]:
    selected_count = int(scope.get("selected_count") or 0)
    outline = [
        "概览",
        "结构化岗位事实",
        "政策证据",
        "风险提示",
        "下一步",
    ]
    if selected_count > 1:
        outline.insert(2, f"岗位对比（{selected_count} 项）")
    if evidence:
        outline.append("证据来源")
    if list(scope.get("visible_columns") or []):
        outline.append("快照字段")
    return outline


def cleanup_analysis_report(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    if cleaned and not cleaned.startswith("# "):
        cleaned = f"# 岗位分析报告\n\n{cleaned}"
    return cleaned


def _build_evidence_queries(
    *,
    title: str,
    filters: dict[str, Any],
    notes: str,
    visible_columns: list[str],
) -> list[str]:
    queries = [
        f"{title} 政策 公告",
        f"{title} 专业目录 招录指南",
    ]
    major = str(filters.get("major") or "").strip()
    if major:
        queries.append(f"{title} {major} 专业要求")
    region = str(filters.get("region") or "").strip()
    if region:
        queries.append(f"{title} {region} 地区政策")
    if notes:
        queries.append(f"{title} {notes}")
    if visible_columns:
        queries.append(f"{title} {','.join(visible_columns[:4])}")
    return _deduplicate_strings(queries)


def _normalize_string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values):
        item = _clean_text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _deduplicate_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _derive_report_title(title: str) -> str:
    normalized = _clean_text(title)
    if not normalized:
        normalized = "岗位分析"
    normalized = re.sub(r"快照$", "", normalized)
    if not normalized.endswith("岗位分析"):
        if normalized.endswith("分析"):
            normalized = normalized[: -len("分析")]
        normalized = f"{normalized}岗位分析"
    return f"{normalized}报告"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned


def _merge_analysis_profile(
    *,
    profile_summary: dict[str, Any],
    filters: dict[str, Any],
    notes: str,
) -> dict[str, Any]:
    merged = dict(profile_summary or {})
    if filters.get("major"):
        merged["major"] = _clean_text(filters.get("major"))
    if filters.get("education"):
        merged["education"] = _clean_text(filters.get("education"))
    if filters.get("degree"):
        merged["degree"] = _clean_text(filters.get("degree"))
    if filters.get("political_status"):
        merged["political_status"] = _clean_text(filters.get("political_status"))

    region = _clean_text(filters.get("region"))
    if region:
        merged["region"] = region
        merged["target_regions"] = _deduplicate_strings(
            [*list(merged.get("target_regions") or []), region]
        )

    department = _clean_text(filters.get("department"))
    if department:
        merged["department"] = department
        merged["desired_departments"] = _deduplicate_strings(
            [*list(merged.get("desired_departments") or []), department]
        )

    job_title = _clean_text(filters.get("job_title"))
    if job_title:
        merged["job_title"] = job_title
        merged["desired_positions"] = _deduplicate_strings(
            [*list(merged.get("desired_positions") or []), job_title]
        )

    merged_notes = [str(merged.get("notes") or "").strip(), notes]
    merged["notes"] = " ".join(part for part in merged_notes if part).strip()
    return merged


def build_position_research_plan(
    *,
    scope: dict[str, Any],
    position_facts: dict[str, Any],
    max_positions: int = 5,
) -> dict[str, Any]:
    selected_positions = list(position_facts.get("selected_positions") or [])
    recommendations = list(position_facts.get("recommendations") or [])
    plan_items: list[dict[str, Any]] = []

    for index, position in enumerate(selected_positions[:max_positions], start=1):
        history_bundle = dict(position.get("history") or {})
        history_summary = dict(history_bundle.get("summary") or {})
        records = list(history_bundle.get("records") or [])
        web_search_needed = (
            len(records) < 2
            or history_summary.get("latest_recruit_count") is None
            or history_summary.get("latest_interview_ratio") is None
        )
        plan_items.append(
            {
                "index": index,
                "position_id": position.get("id"),
                "department_name": position.get("department_name"),
                "job_title": position.get("job_title"),
                "position_code": position.get("position_code"),
                "focus": [
                    "岗位硬条件是否满足",
                    "近年招录人数趋势",
                    "报录比/竞争强度趋势",
                    "备注与政策风险",
                ],
                "needs_web_search": web_search_needed,
            }
        )

    return {
        "analysis_goal": scope.get("analysis_goal") or "",
        "query": scope.get("query") or "",
        "selected_count": len(selected_positions),
        "recommendation_count": len(recommendations),
        "plan_items": plan_items,
        "exploration_guidance": [
            "优先看本地岗位历史和政策证据，再决定是否需要外部检索",
            "对每个岗位独立形成结论，不要把多个岗位合并成一段泛泛结论",
            "如果历史招录或报录比缺失，必须明确说明缺口并给出补证据方式",
        ],
    }


def build_analysis_strategy(
    scope: dict[str, Any],
    *,
    position_facts: dict[str, Any],
    policy_evidence: list[dict[str, Any]] | None = None,
    max_positions: int = 5,
) -> dict[str, Any]:
    selected_positions = list(position_facts.get("selected_positions") or [])
    recommendations = list(position_facts.get("recommendations") or [])
    source_positions = selected_positions or recommendations
    source_positions = list(source_positions[:max_positions])
    policy_evidence = list(policy_evidence or [])

    research_plan = build_position_research_plan(
        scope=scope,
        position_facts=position_facts,
        max_positions=max_positions,
    )

    research_targets: list[dict[str, Any]] = []
    sparse_target_count = 0
    for item in list(research_plan.get("plan_items") or []):
        matched_position = _match_strategy_position(
            source_positions,
            item.get("position_id"),
        )
        history_bundle = dict((matched_position or {}).get("history") or {})
        history_summary = summarize_position_history(history_bundle)
        needs_web_search = bool(item.get("needs_web_search")) or history_summary.get(
            "record_count", 0
        ) < 2
        if history_summary.get("latest_interview_ratio") is None:
            needs_web_search = True
        if needs_web_search:
            sparse_target_count += 1
        research_targets.append(
            {
                **item,
                "history_summary": history_summary,
                "history_priority": "high" if not needs_web_search else "low",
                "needs_web_search": needs_web_search,
                "focus": [
                    "岗位硬条件是否满足",
                    "历史招录",
                    "报录比趋势",
                    "政策与备注风险",
                    *(["外网补证"] if needs_web_search else []),
                ],
            }
        )

    all_history_rich = bool(research_targets) and sparse_target_count == 0
    strategy_name = "history_first" if all_history_rich else "explore_then_verify"
    needs_web_search = any(item.get("needs_web_search") for item in research_targets)

    return {
        "strategy_name": strategy_name,
        "planning_strategy": "plan_and_solve",
        "evidence_strategy": "react",
        "decision_style": strategy_name,
        "analysis_goal": scope.get("analysis_goal") or "",
        "query": scope.get("query") or "",
        "research_budget": {
            "selected_count": len(selected_positions),
            "recommendation_count": len(recommendations),
            "max_positions": max_positions,
            "web_search_enabled": needs_web_search,
            "policy_evidence_count": len(policy_evidence),
        },
        "priority_sources": [
            "postgres_history",
            "milvus_policy",
            *(["web_search"] if needs_web_search else []),
        ],
        "research_targets": research_targets,
        "research_plan": research_plan,
        "summary_lines": [
            f"策略模式: {strategy_name}",
            "规划方式: plan_and_solve",
            "补证方式: react",
            f"历史充分: {'是' if all_history_rich else '否'}",
            f"政策证据数: {len(policy_evidence)}",
        ],
    }


def summarize_position_history(
    history: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(history or {})
    records = list(payload.get("records") or [])
    summary = dict(payload.get("summary") or {})
    years = summary.get("history_years") or [
        item.get("year") for item in records if item.get("year") is not None
    ]
    notes: list[str] = []
    if summary.get("record_count", 0) == 0:
        notes.append("本地岗位库里暂未找到同岗历史记录")
    else:
        recruit_count = summary.get("latest_recruit_count")
        interview_ratio = summary.get("latest_interview_ratio")
        if recruit_count is not None:
            notes.append(f"最近一期招录人数约 {recruit_count}")
        if interview_ratio is not None:
            notes.append(f"最近一期报录比约 {interview_ratio:.2f}:1")
        if summary.get("recruit_count_trend") == "upward":
            notes.append("招录人数呈上升趋势")
        elif summary.get("recruit_count_trend") == "downward":
            notes.append("招录人数呈下降趋势")
        if summary.get("interview_ratio_trend") == "upward":
            notes.append("竞争强度在减弱")
        elif summary.get("interview_ratio_trend") == "downward":
            notes.append("竞争强度在增强")

    return {
        "match_basis": payload.get("match_basis"),
        "record_count": int(summary.get("record_count") or len(records)),
        "history_years": [year for year in years if year is not None],
        "latest_recruit_count": summary.get("latest_recruit_count"),
        "latest_interview_ratio": summary.get("latest_interview_ratio"),
        "recruit_count_trend": summary.get("recruit_count_trend", "unknown"),
        "interview_ratio_trend": summary.get("interview_ratio_trend", "unknown"),
        "notes": notes,
        "records": records,
    }


def _match_strategy_position(
    positions: list[dict[str, Any]],
    position_id: Any,
) -> dict[str, Any] | None:
    normalized_position_id = _clean_text(position_id)
    if not normalized_position_id:
        return None
    for position in positions:
        current_id = _clean_text(position.get("position_id") or position.get("id"))
        if current_id == normalized_position_id:
            return position
    return None

