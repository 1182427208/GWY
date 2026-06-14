from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any


_EDUCATION_ORDER = {
    "不限": 0,
    "大专": 1,
    "专科": 1,
    "高职": 1,
    "本科": 2,
    "学士": 2,
    "研究生": 3,
    "硕士": 3,
    "博士": 4,
}

_DEGREE_ORDER = {
    "不限": 0,
    "无": 0,
    "大专": 1,
    "专科": 1,
    "学士": 2,
    "本科": 2,
    "硕士": 3,
    "博士": 4,
}

_MAJOR_UNLIMITED_HINTS = (
    "不限",
    "不限专业",
    "专业不限",
    "无专业限制",
    "专业要求不限",
)

_REGION_STRICT_HINTS = ("只看", "仅看", "限定", "必须", "只要", "仅要")


@dataclass(slots=True)
class PositionRecommendationCriteria:
    query: str
    major: str | None = None
    education: str | None = None
    degree: str | None = None
    political_status: str | None = None
    is_fresh_graduate: bool | None = None
    grassroots_experience_years: int | None = None
    target_regions: list[str] = field(default_factory=list)
    avoid_conditions: list[str] = field(default_factory=list)
    desired_departments: list[str] = field(default_factory=list)
    desired_positions: list[str] = field(default_factory=list)
    excluded_positions: list[str] = field(default_factory=list)
    strict_region: bool = False
    missing_fields: list[str] = field(default_factory=list)
    profile_summary: dict[str, Any] = field(default_factory=dict)


def extract_position_recommendation_criteria(
    query: str,
    profile: Any | None = None,
) -> PositionRecommendationCriteria:
    normalized_query = _normalize_text(query)
    profile_summary = build_profile_summary(profile)

    major = _first_non_empty(
        profile_summary.get("major"),
        _extract_major_from_query(normalized_query),
    )
    education = _first_non_empty(
        profile_summary.get("education"),
        _extract_keyword_from_query(normalized_query, _EDUCATION_ORDER.keys()),
    )
    degree = _first_non_empty(
        profile_summary.get("degree"),
        _extract_keyword_from_query(normalized_query, _DEGREE_ORDER.keys()),
    )
    political_status = _first_non_empty(
        profile_summary.get("political_status"),
        _extract_keyword_from_query(
            normalized_query,
            ("中共党员", "党员", "群众", "共青团员", "预备党员"),
        ),
    )

    grassroots_years = profile_summary.get("grassroots_experience_years")
    if grassroots_years is None:
        grassroots_years = _extract_grassroots_years_from_query(normalized_query)

    target_regions = list(profile_summary.get("target_regions") or [])
    target_regions.extend(_extract_regions_from_query(normalized_query))
    target_regions = _deduplicate(target_regions)

    avoid_conditions = _deduplicate(
        [
            *list(profile_summary.get("avoid_conditions") or []),
            *_extract_keywords_after_marker(
                normalized_query,
                ("鎺掗櫎", "涓嶈", "涓嶈€冭檻"),
            ),
        ]
    )

    desired_departments = _deduplicate(
        [
            *list(profile_summary.get("desired_departments") or []),
            *_extract_keywords_after_marker(normalized_query, ("部门", "单位", "机构")),
        ]
    )
    desired_positions = _deduplicate(
        [
            *list(profile_summary.get("desired_positions") or []),
            *_extract_keywords_after_marker(normalized_query, ("岗位名称", "职位名称")),
        ]
    )
    excluded_positions = _deduplicate(
        [
            *list(profile_summary.get("excluded_positions") or []),
            *_extract_keywords_after_marker(normalized_query, ("排除", "不要", "不考虑")),
        ]
    )

    strict_region = any(hint in normalized_query for hint in _REGION_STRICT_HINTS)

    missing_fields: list[str] = []
    if not major:
        missing_fields.append("major")
    if not education:
        missing_fields.append("education")
    if not degree:
        missing_fields.append("degree")

    return PositionRecommendationCriteria(
        query=query,
        major=major,
        education=education,
        degree=degree,
        political_status=political_status,
        is_fresh_graduate=profile_summary.get("is_fresh_graduate"),
        grassroots_experience_years=grassroots_years,
        target_regions=target_regions,
        avoid_conditions=avoid_conditions,
        desired_departments=desired_departments,
        desired_positions=desired_positions,
        excluded_positions=excluded_positions,
        strict_region=strict_region,
        missing_fields=missing_fields,
        profile_summary=profile_summary,
    )


def build_profile_summary(profile: Any | None) -> dict[str, Any]:
    if profile is None:
        return {}
    summary = {
        "major": _get_value(profile, "major"),
        "education": _get_value(profile, "education"),
        "degree": _get_value(profile, "degree"),
        "political_status": _get_value(profile, "political_status"),
        "is_fresh_graduate": _get_value(profile, "is_fresh_graduate"),
        "grassroots_experience_years": _get_value(
            profile, "grassroots_experience_years"
        ),
        "target_regions": list(_get_value(profile, "target_regions") or []),
        "avoid_conditions": list(_get_value(profile, "avoid_conditions") or []),
        "desired_departments": list(_get_value(profile, "desired_departments") or []),
        "desired_positions": list(_get_value(profile, "desired_positions") or []),
        "excluded_positions": list(_get_value(profile, "excluded_positions") or []),
        "daily_study_hours": _get_value(profile, "daily_study_hours"),
        "notes": _get_value(profile, "notes"),
    }
    return summary


def position_to_dict(position: Any) -> dict[str, Any]:
    data = {
        "id": str(_get_value(position, "id") or ""),
        "department_code": _get_value(position, "department_code"),
        "department_name": _get_value(position, "department_name"),
        "office_name": _get_value(position, "office_name"),
        "institution_type": _get_value(position, "institution_type"),
        "job_title": _get_value(position, "job_title"),
        "position_attribute": _get_value(position, "position_attribute"),
        "position_distribution": _get_value(position, "position_distribution"),
        "position_desc": _get_value(position, "position_desc"),
        "position_code": _get_value(position, "position_code"),
        "institution_level": _get_value(position, "institution_level"),
        "exam_category": _get_value(position, "exam_category"),
        "recruit_count": _get_value(position, "recruit_count"),
        "major_requirement": _get_value(position, "major_requirement"),
        "education_requirement": _get_value(position, "education_requirement"),
        "degree_requirement": _get_value(position, "degree_requirement"),
        "political_status_requirement": _get_value(
            position, "political_status_requirement"
        ),
        "grassroots_years_requirement": _get_value(
            position, "grassroots_years_requirement"
        ),
        "grassroots_project_experience": _get_value(
            position, "grassroots_project_experience"
        ),
        "professional_test_in_interview": _get_value(
            position, "professional_test_in_interview"
        ),
        "interview_ratio": _get_value(position, "interview_ratio"),
        "work_location": _get_value(position, "work_location"),
        "household_registration_location": _get_value(
            position, "household_registration_location"
        ),
        "remarks": _get_value(position, "remarks"),
        "department_website": _get_value(position, "department_website"),
        "contact_phone_1": _get_value(position, "contact_phone_1"),
        "contact_phone_2": _get_value(position, "contact_phone_2"),
        "contact_phone_3": _get_value(position, "contact_phone_3"),
        "source_file": _get_value(position, "source_file"),
        "source_sheet": _get_value(position, "source_sheet"),
        "source_row_number": _get_value(position, "source_row_number"),
        "raw_data": dict(_get_value(position, "raw_data") or {}),
    }
    data["search_text"] = " ".join(
        str(value)
        for key, value in data.items()
        if key
        not in {
            "id",
            "raw_data",
            "search_text",
            "source_row_number",
        }
        and value not in (None, "")
    )
    return data


def position_passes_hard_filters(
    position: Any,
    criteria: PositionRecommendationCriteria,
) -> tuple[bool, list[str], list[str]]:
    position_dict = position_to_dict(position)
    reasons: list[str] = []
    risks: list[str] = []

    if criteria.excluded_positions and _matches_any(
        position_dict,
        criteria.excluded_positions,
    ):
        return False, ["命中排除条件"], ["用户已明确排除该岗位"]

    if criteria.avoid_conditions and _matches_any(
        position_dict,
        criteria.avoid_conditions,
    ):
        return False, ["鍛戒腑閬垮厤鏉′欢"], ["鍏抽敭璇嶅懡涓凡閬垮厤鏉′欢"]

    if criteria.desired_positions and not _matches_any(
        position_dict,
        criteria.desired_positions,
    ):
        risks.append("未命中用户显式偏好岗位")

    if criteria.desired_departments and not _matches_any(
        position_dict,
        criteria.desired_departments,
    ):
        risks.append("未命中用户显式偏好部门")

    if criteria.strict_region and criteria.target_regions:
        if not _matches_any(position_dict, criteria.target_regions):
            return False, ["不满足用户指定地区"], ["地区要求与用户偏好不一致"]

    if not _match_education(
        criteria.education,
        position_dict.get("education_requirement"),
    ):
        return False, ["学历不满足"], ["学历门槛不满足"]

    if not _match_degree(criteria.degree, position_dict.get("degree_requirement")):
        return False, ["学位不满足"], ["学位门槛不满足"]

    if not _match_political_status(
        criteria.political_status,
        position_dict.get("political_status_requirement"),
    ):
        return False, ["政治面貌不满足"], ["政治面貌限制不满足"]

    if not _match_grassroots(
        criteria.grassroots_experience_years,
        position_dict.get("grassroots_years_requirement"),
    ):
        return False, ["基层工作经历不满足"], ["基层工作经历限制不满足"]

    if criteria.major and not _match_major_requirement(
        criteria.major, position_dict.get("major_requirement")
    ):
        return False, ["专业不满足"], ["专业要求不满足"]

    if criteria.is_fresh_graduate is False and _requires_fresh_graduate(position_dict):
        return False, ["岗位限制应届生"], ["岗位限制应届生"]

    if criteria.is_fresh_graduate is True and _forbids_fresh_graduate(position_dict):
        return False, ["岗位限制非应届"], ["岗位限制非应届"]

    if position_dict.get("remarks"):
        remark_text = _normalize_text(str(position_dict["remarks"]))
        if any(token in remark_text for token in ("以官方为准", "电话确认", "需确认")):
            risks.append("备注存在人工核实项")
        if any(token in remark_text for token in ("仅限", "限", "不得", "不得报考")):
            reasons.append("备注包含明确限制条件")

    return True, reasons, risks


def score_position(
    position: Any,
    criteria: PositionRecommendationCriteria,
) -> dict[str, Any]:
    position_dict = position_to_dict(position)
    score = 60.0
    reasons: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []

    if criteria.major and _match_major_requirement(
        criteria.major, position_dict.get("major_requirement")
    ):
        score += 22
        reasons.append({"type": "major_match", "text": "专业条件匹配"})

    if criteria.education and _match_education(
        criteria.education, position_dict.get("education_requirement")
    ):
        score += 12
        reasons.append({"type": "education_match", "text": "学历条件匹配"})

    if criteria.degree and _match_degree(
        criteria.degree, position_dict.get("degree_requirement")
    ):
        score += 8
        reasons.append({"type": "degree_match", "text": "学位条件匹配"})

    if criteria.political_status and _match_political_status(
        criteria.political_status, position_dict.get("political_status_requirement")
    ):
        score += 8
        reasons.append({"type": "political_match", "text": "政治面貌条件匹配"})

    if criteria.grassroots_experience_years is not None and _match_grassroots(
        criteria.grassroots_experience_years,
        position_dict.get("grassroots_years_requirement"),
    ):
        score += 8
        reasons.append({"type": "grassroots_match", "text": "基层工作经历条件匹配"})

    if criteria.target_regions and _matches_any(position_dict, criteria.target_regions):
        score += 8
        reasons.append({"type": "region_match", "text": "地区偏好匹配"})

    if criteria.desired_departments and _matches_any(
        position_dict,
        criteria.desired_departments,
    ):
        score += 6
        reasons.append({"type": "department_match", "text": "部门偏好匹配"})

    if criteria.desired_positions and _matches_any(
        position_dict,
        criteria.desired_positions,
    ):
        score += 6
        reasons.append({"type": "position_match", "text": "岗位关键词匹配"})

    recruit_count = _safe_float(position_dict.get("recruit_count"))
    if recruit_count:
        score += min(6.0, math.log1p(recruit_count))

    if position_dict.get("professional_test_in_interview") in {"是", "有"}:
        score -= 4
        risks.append({"type": "professional_test", "text": "面试阶段可能有专业能力测试"})

    ratio_text = str(position_dict.get("interview_ratio") or "").strip()
    if ratio_text:
        ratio_value = _parse_ratio(ratio_text)
        if ratio_value is not None:
            if ratio_value <= 0.1:
                score -= 3
                risks.append({"type": "competition", "text": "面试竞争较强"})
            elif ratio_value >= 0.2:
                score += 2

    remark_text = _normalize_text(str(position_dict.get("remarks") or ""))
    if remark_text:
        if any(token in remark_text for token in ("电话确认", "以官方为准", "请咨询", "需确认")):
            score -= 2
            risks.append({"type": "manual_confirm", "text": "备注需要人工复核"})
        if any(token in remark_text for token in ("应届", "限", "仅限")):
            score -= 2

    score = max(0.0, min(100.0, score))
    recommend_level = _recommend_level(score)
    risk_level = _risk_level(score, risks)
    need_manual_confirm = bool(risks or any(reason for reason in reasons if reason))

    return {
        "score": round(score, 2),
        "recommend_level": recommend_level,
        "risk_level": risk_level,
        "need_manual_confirm": need_manual_confirm,
        "reasons": reasons,
        "risks": risks,
    }


def build_position_brief(
    position: dict[str, Any],
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "position_id": position.get("id"),
        "department_name": position.get("department_name"),
        "office_name": position.get("office_name"),
        "job_title": position.get("job_title"),
        "position_code": position.get("position_code"),
        "work_location": position.get("work_location"),
        "household_registration_location": position.get(
            "household_registration_location"
        ),
        "education_requirement": position.get("education_requirement"),
        "degree_requirement": position.get("degree_requirement"),
        "major_requirement": position.get("major_requirement"),
        "political_status_requirement": position.get("political_status_requirement"),
        "grassroots_years_requirement": position.get("grassroots_years_requirement"),
        "recruit_count": position.get("recruit_count"),
        "remarks": position.get("remarks"),
        "department_website": position.get("department_website"),
        "contact_phone_1": position.get("contact_phone_1"),
        "contact_phone_2": position.get("contact_phone_2"),
        "contact_phone_3": position.get("contact_phone_3"),
        **recommendation,
    }


def build_recommendation_summary(
    criteria: PositionRecommendationCriteria,
    recommendations: list[dict[str, Any]],
    *,
    candidate_count: int,
    filtered_count: int,
) -> dict[str, Any]:
    return {
        "query": criteria.query,
        "profile_summary": criteria.profile_summary,
        "missing_fields": list(criteria.missing_fields),
        "candidate_count": candidate_count,
        "filtered_count": filtered_count,
        "recommendation_count": len(recommendations),
        "top_positions": [
            {
                "department_name": item.get("department_name"),
                "job_title": item.get("job_title"),
                "position_code": item.get("position_code"),
                "score": item.get("score"),
                "recommend_level": item.get("recommend_level"),
            }
            for item in recommendations[:5]
        ],
    }


def _recommend_level(score: float) -> str:
    if score >= 85:
        return "strong_match"
    if score >= 72:
        return "good_match"
    if score >= 60:
        return "borderline_match"
    return "weak_match"


def _risk_level(score: float, risks: list[dict[str, Any]]) -> str:
    if score >= 85 and not risks:
        return "low"
    if score >= 70 and len(risks) <= 1:
        return "medium"
    return "high"


def _match_education(user_level: str | None, requirement: str | None) -> bool:
    if not requirement:
        return True
    normalized_requirement = _normalize_text(str(requirement))
    if any(hint in normalized_requirement for hint in _MAJOR_UNLIMITED_HINTS):
        return True
    requirement_rank = _resolve_requirement_rank(normalized_requirement, _EDUCATION_ORDER)
    user_rank = _resolve_requirement_rank(_normalize_text(user_level or ""), _EDUCATION_ORDER)
    if user_rank == 0:
        return True
    if requirement_rank == 0:
        return True
    return user_rank >= requirement_rank


def _match_degree(user_level: str | None, requirement: str | None) -> bool:
    if not requirement:
        return True
    normalized_requirement = _normalize_text(str(requirement))
    if any(hint in normalized_requirement for hint in _MAJOR_UNLIMITED_HINTS):
        return True
    requirement_rank = _resolve_requirement_rank(normalized_requirement, _DEGREE_ORDER)
    user_rank = _resolve_requirement_rank(_normalize_text(user_level or ""), _DEGREE_ORDER)
    if user_rank == 0:
        return True
    if requirement_rank == 0:
        return True
    return user_rank >= requirement_rank


def _match_political_status(user_status: str | None, requirement: str | None) -> bool:
    if not requirement:
        return True
    normalized_requirement = _normalize_text(str(requirement))
    if any(hint in normalized_requirement for hint in ("不限", "无要求", "不限政治面貌")):
        return True
    if not user_status:
        return True
    normalized_user = _normalize_text(str(user_status))
    if "党员" in normalized_requirement and "党员" in normalized_user:
        return True
    if "群众" in normalized_requirement and "群众" in normalized_user:
        return True
    return normalized_user in normalized_requirement or normalized_requirement in normalized_user


def _match_grassroots(user_years: int | None, requirement: str | None) -> bool:
    if not requirement:
        return True
    normalized_requirement = _normalize_text(str(requirement))
    if any(hint in normalized_requirement for hint in ("不限", "无", "没有")):
        return True
    required_years = _parse_years_requirement(normalized_requirement)
    if required_years is None:
        return True
    if user_years is None:
        return True
    return user_years >= required_years


def _match_major_requirement(user_major: str | None, requirement: str | None) -> bool:
    if not requirement:
        return True
    normalized_requirement = _normalize_text(str(requirement))
    if any(hint in normalized_requirement for hint in _MAJOR_UNLIMITED_HINTS):
        return True
    if not user_major:
        return True
    normalized_user = _normalize_text(str(user_major))
    requirement_parts = _split_requirement_text(normalized_requirement)
    if normalized_user in normalized_requirement:
        return True
    for token in _major_requirement_search_terms(normalized_user):
        if token and token in normalized_requirement:
            return True
    return any(part and part in normalized_user for part in requirement_parts)


def _major_requirement_search_terms(user_major: str) -> list[str]:
    normalized = _normalize_text(user_major)
    family_terms: dict[str, list[str]] = {
        "工学": [
            "08",
            "工程",
            "土木",
            "建筑",
            "机械",
            "材料",
            "电气",
            "电子",
            "信息",
            "自动化",
            "计算机",
            "通信",
            "软件",
            "网络",
            "交通",
            "水利",
            "环境",
            "化工",
            "安全",
            "能源",
            "测绘",
            "地质",
            "矿业",
            "航空",
            "航天",
            "纺织",
            "轻工",
            "食品",
        ],
        "法学": ["03", "法学", "法律", "法理", "宪法", "行政法", "民商法", "刑法"],
        "经济学": ["02", "经济", "财政", "金融", "贸易", "审计", "资产评估"],
        "管理学": ["12", "管理", "会计", "财务", "工商", "公共管理", "行政管理"],
        "文学": ["05", "文学", "语言", "新闻", "传播", "汉语言", "外语"],
        "理学": ["07", "数学", "物理", "化学", "生物", "统计", "地理", "理学"],
        "医学": ["10", "医学", "临床", "药学", "护理", "公共卫生", "口腔"],
        "教育学": ["04", "教育", "师范", "心理", "体育"],
        "农学": ["09", "农学", "园艺", "植物", "动物", "林学", "水产", "农业"],
        "哲学": ["01", "哲学", "马克思主义"],
        "历史学": ["06", "历史", "考古", "中国史", "世界史"],
        "艺术学": ["13", "艺术", "美术", "设计", "音乐", "戏剧", "舞蹈", "广播电视"],
    }
    terms = [normalized]
    for key, values in family_terms.items():
        if key in normalized:
            terms.extend(values)
            break
    else:
        if normalized.startswith("08") or "工学" in normalized:
            terms.extend(family_terms["工学"])
    return list(dict.fromkeys(term for term in terms if term))


def _requires_fresh_graduate(position: Any) -> bool:
    text = " ".join(
        _normalize_text(str(_get_value(position, field) or ""))
        for field in ("remarks", "position_desc", "position_attribute")
    )
    return any(token in text for token in ("应届", "2026届", "2026应届"))


def _forbids_fresh_graduate(position: Any) -> bool:
    text = " ".join(
        _normalize_text(str(_get_value(position, field) or ""))
        for field in ("remarks", "position_desc", "position_attribute")
    )
    return any(token in text for token in ("非应届", "往届", "社会在职", "社会人员"))


def _matches_any(position_dict: dict[str, Any], tokens: list[str]) -> bool:
    if not tokens:
        return False
    searchable = " ".join(
        _normalize_text(str(position_dict.get(field) or ""))
        for field in (
            "department_code",
            "department_name",
            "office_name",
            "institution_type",
            "job_title",
            "position_attribute",
            "position_distribution",
            "position_desc",
            "position_code",
            "institution_level",
            "exam_category",
            "major_requirement",
            "education_requirement",
            "degree_requirement",
            "political_status_requirement",
            "grassroots_years_requirement",
            "grassroots_project_experience",
            "work_location",
            "household_registration_location",
            "remarks",
            "source_file",
            "source_sheet",
        )
    )
    return any(_normalize_text(token) and _normalize_text(token) in searchable for token in tokens)


def _extract_major_from_query(query: str) -> str | None:
    patterns = [
        r"专业[是为：: ]*([^，。,；;、\n]{2,30})",
        r"学的是([^，。,；;、\n]{2,30})",
        r"我的专业是([^，。,；;、\n]{2,30})",
    ]
    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            candidate = _normalize_text(match.group(1))
            if candidate:
                return candidate
    return None


def _extract_keyword_from_query(query: str, keywords: Any) -> str | None:
    for keyword in keywords:
        if keyword in query:
            return str(keyword)
    return None


def _extract_keywords_after_marker(query: str, markers: tuple[str, ...]) -> list[str]:
    results: list[str] = []
    for marker in markers:
        pattern = rf"{re.escape(marker)}[是为：: ]*([^，。,；;、\n]{2,40})"
        match = re.search(pattern, query)
        if match:
            candidate = _normalize_text(match.group(1))
            if candidate:
                results.append(candidate)
    return results


def _extract_grassroots_years_from_query(query: str) -> int | None:
    match = re.search(r"(\d+)\s*年", query)
    if match and any(token in query for token in ("基层", "基层工作", "基层经历", "服务基层")):
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _extract_regions_from_query(query: str) -> list[str]:
    region_keywords = (
        "北京",
        "天津",
        "河北",
        "山西",
        "内蒙古",
        "辽宁",
        "吉林",
        "黑龙江",
        "上海",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "广西",
        "海南",
        "重庆",
        "四川",
        "贵州",
        "云南",
        "西藏",
        "陕西",
        "甘肃",
        "青海",
        "宁夏",
        "新疆",
        "中央",
        "国考",
    )
    return [keyword for keyword in region_keywords if keyword in query]


def _parse_years_requirement(text: str) -> int | None:
    match = re.search(r"(\d+)\s*年", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _parse_ratio(text: str) -> float | None:
    ratio_match = re.search(r"(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)", text)
    if ratio_match:
        left = float(ratio_match.group(1))
        right = float(ratio_match.group(2))
        if right == 0:
            return None
        return left / right
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent_match:
        return float(percent_match.group(1)) / 100.0
    return None


def _resolve_requirement_rank(text: str, order_map: dict[str, int]) -> int:
    if not text:
        return 0
    for keyword, rank in sorted(order_map.items(), key=lambda item: len(item[0]), reverse=True):
        if keyword != "不限" and keyword in text:
            return rank
    if any(hint in text for hint in ("不限", "无要求", "不限学历", "不限学位")):
        return 0
    return 0


def _split_requirement_text(text: str) -> list[str]:
    tokens = re.split(r"[、,，;；/\n]|(?:以及)|(?:和)", text)
    return [token.strip() for token in tokens if token.strip()]


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s+", "", str(text))
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    return cleaned


def _deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(value)
    return unique


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return str(value)
    return None


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _get_value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
