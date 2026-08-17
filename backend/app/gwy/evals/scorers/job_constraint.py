from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.gwy.evals.normalization import normalize_value
from app.gwy.evals.schemas import AgentObservation, EvalCase, ScoreBundle


@dataclass(slots=True)
class JobConstraintScore:
    constraint_violation_rate: float
    job_precision: float
    job_recall: float
    job_f1: float
    violations: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    failure_reasons: list[str] = field(default_factory=list)

    def bundle(self) -> ScoreBundle:
        return ScoreBundle(
            name="job_constraint",
            passed=self.passed,
            metrics={
                "constraint_violation_rate": self.constraint_violation_rate,
                "job_precision": self.job_precision,
                "job_recall": self.job_recall,
                "job_f1": self.job_f1,
            },
            failure_reasons=self.failure_reasons,
            details={"violations": self.violations},
        )


def score_job_constraints(
    case: EvalCase, observation: AgentObservation
) -> JobConstraintScore:
    expected_ids = set(case.expected.job_ids)
    forbidden_ids = set(case.expected.forbidden_job_ids)
    returned_ids = [str(item) for item in observation.returned_job_ids]
    returned_set = set(returned_ids)
    violations: list[dict[str, Any]] = []

    for job_id in sorted(forbidden_ids & returned_set):
        violations.append(
            {
                "job_id": job_id,
                "field": "forbidden_job_ids",
                "reason": "job is explicitly forbidden by ground truth",
            }
        )

    profile = dict(case.profile or {})
    for job in observation.returned_jobs:
        job_id = str(job.get("id") or job.get("position_id") or "")
        if not job_id or job_id in forbidden_ids:
            continue
        for item in _check_hard_constraints(profile, job):
            violations.append({"job_id": job_id, **item})

    violating_jobs = {item["job_id"] for item in violations}
    violation_rate = len(violating_jobs) / len(returned_set) if returned_set else 0.0
    precision = (
        len(expected_ids & returned_set) / len(returned_set)
        if returned_set and expected_ids
        else (1.0 if not returned_set and not expected_ids else 0.0)
    )
    recall = (
        len(expected_ids & returned_set) / len(expected_ids) if expected_ids else 1.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    failures = [f"{len(violations)} job constraint violation(s)"] if violations else []
    return JobConstraintScore(
        constraint_violation_rate=violation_rate,
        job_precision=precision,
        job_recall=recall,
        job_f1=f1,
        violations=violations,
        passed=not failures,
        failure_reasons=failures,
    )


def _check_hard_constraints(
    profile: dict[str, Any], job: dict[str, Any]
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    user_political = str(profile.get("political_status") or "")
    political_req = str(job.get("political_status_requirement") or "")
    if (
        political_req
        and "不限" not in political_req
        and "党员" in political_req
        and "党员" not in user_political
    ):
        violations.append(
            _violation("political_status_requirement", user_political, political_req)
        )

    user_major = str(profile.get("major") or "")
    major_req = str(job.get("major_requirement") or "")
    if user_major and major_req and "不限" not in major_req:
        if not _major_matches(user_major, major_req):
            violations.append(_violation("major_requirement", user_major, major_req))

    education = str(profile.get("education") or "")
    education_req = str(job.get("education_requirement") or "")
    if education and education_req and not _education_meets(education, education_req):
        violations.append(_violation("education_requirement", education, education_req))

    degree = str(profile.get("degree") or "")
    degree_req = str(job.get("degree_requirement") or "")
    if (
        degree
        and degree_req
        and "不限" not in degree_req
        and not _degree_meets(degree, degree_req)
    ):
        violations.append(_violation("degree_requirement", degree, degree_req))

    user_years = _years(profile.get("grassroots_years"))
    required_years = _years(job.get("grassroots_years_requirement"))
    if required_years is not None and (
        user_years is None or user_years < required_years
    ):
        violations.append(
            _violation("grassroots_years_requirement", user_years, required_years)
        )

    project_req = str(job.get("grassroots_project_experience") or "")
    has_project = bool(profile.get("grassroots_project_experience"))
    if project_req and "不限" not in project_req and not has_project:
        violations.append(
            _violation("grassroots_project_experience", has_project, project_req)
        )

    regions = [str(item) for item in profile.get("target_regions") or [] if str(item)]
    location = " ".join(
        str(job.get(key) or "")
        for key in (
            "work_location",
            "household_registration_location",
            "position_distribution",
        )
    )
    if regions and location and not any(region in location for region in regions):
        violations.append(_violation("work_location", regions, location))
    return violations


def _violation(field: str, user_value: Any, job_requirement: Any) -> dict[str, Any]:
    return {
        "field": field,
        "user_value": user_value,
        "job_requirement": job_requirement,
    }


def _major_matches(user_major: str, requirement: str) -> bool:
    if user_major in requirement:
        return True
    for token in re.split(r"[,，、;；/或 ]+", requirement):
        if token and token in user_major:
            return True
    return any(
        token in user_major
        for token in ("计算机", "法学", "经济", "汉语言")
        if token in requirement
    )


def _education_meets(user: str, requirement: str) -> bool:
    levels = {
        "高中": 1,
        "大专": 2,
        "专科": 2,
        "本科": 3,
        "硕士": 4,
        "研究生": 4,
        "博士": 5,
    }
    user_level = max(
        (level for name, level in levels.items() if name in user), default=0
    )
    required_level = max(
        (level for name, level in levels.items() if name in requirement), default=0
    )
    return required_level == 0 or user_level >= required_level


def _degree_meets(user: str, requirement: str) -> bool:
    normalized_user = str(normalize_value(user))
    normalized_req = str(normalize_value(requirement))
    return normalized_user in normalized_req or normalized_req in normalized_user


def _years(value: Any) -> int | None:
    if value is None or value is False or value == "":
        return 0
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None
