"""Study plan generation helpers (pure functions, no I/O)."""

from __future__ import annotations

import datetime
from typing import Any

# Constants with Chinese names - use unicode escapes
_XINGCE_MODULES: dict[str, list[str]] = {
    "言语理解与表达": [
        "逻辑填空", "片段阅读", "语句表达",
    ],
    "数量关系": [
        "数字推理", "数学运算",
    ],
    "判断推理": [
        "图形推理", "定义判断", "类比推理", "逻辑判断",
    ],
    "资料分析": [
        "增长量/增长率", "比重/倍数/平均数", "综合分析",
    ],
    "常识判断": [
        "政治常识", "法律常识", "经济常识", "文史常识", "科技常识",
    ],
}

_SHENLUN_MODULES: dict[str, list[str]] = {
    "归纳概括": ["单一概括", "综合概括"],
    "提出对策": ["直接对策", "间接反推"],
    "综合分析": ["词句理解", "评价分析", "启示分析"],
    "贯彻执行": ["法定公文", "事务文书"],
    "大作文": ["命题作文", "话题作文", "材料作文"],
}

_DEFAULT_DAILY_STUDY_HOURS = {
    "基础期": 4,
    "强化期": 6,
    "冲刺期": 8,
}


def analyze_exam_subjects(
    *,
    recommendations: list[dict[str, Any]],
    user_profile: dict[str, Any] | None = None,
    exam_type: str = "国考",
) -> dict[str, Any]:
    """Derive required exam subjects from position recommendations and user profile."""
    subjects: dict[str, dict[str, Any]] = {
        "行测": {
            "category": "行测",
            "modules": _XINGCE_MODULES,
            "weight": 50,
            "hours": 0,
        },
        "申论": {
            "category": "申论",
            "modules": _SHENLUN_MODULES,
            "weight": 50,
            "hours": 0,
        },
    }

    has_professional = False
    for rec in (recommendations or []):
        exam_cat = str(rec.get("exam_category", "") or "")
        if "专业科目" in exam_cat or "专业" in exam_cat:
            has_professional = True
            break

    if has_professional:
        subjects["专业科目"] = {
            "category": "专业科目",
            "modules": {"专业知识": ["基础理论", "实务操作", "政策法规"]},
            "weight": 0,
            "hours": 0,
        }
        subjects["行测"]["weight"] = 40
        subjects["申论"]["weight"] = 40
        subjects["专业科目"]["weight"] = 20

    return {"exam_type": exam_type, "subjects": subjects}


def estimate_exam_date(*, exam_year: int | None = None) -> datetime.date:
    """Estimate national exam date (typically last Sunday of November)."""
    if exam_year is None:
        exam_year = datetime.date.today().year
    nov30 = datetime.date(exam_year, 11, 30)
    offset = (6 - nov30.weekday()) % 7
    return nov30 - datetime.timedelta(days=offset)


def generate_phase_schedule(
    *,
    exam_date: datetime.date,
    start_date: datetime.date | None = None,
    study_hours_per_day: int = 4,
    user_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate 3-phase study schedule: foundation, reinforcement, sprint."""
    if start_date is None:
        start_date = datetime.date.today()
    days_until_exam = (exam_date - start_date).days
    if days_until_exam <= 0:
        days_until_exam = 90

    total_weeks = max(4, days_until_exam // 7)
    foundation_weeks = max(2, total_weeks * 4 // 12)
    reinforcement_weeks = max(2, total_weeks * 4 // 12)
    sprint_weeks = total_weeks - foundation_weeks - reinforcement_weeks
    if sprint_weeks < 2:
        sprint_weeks = 2
        reinforcement_weeks = max(2, reinforcement_weeks - 1)

    phases: list[dict[str, Any]] = [
        {
            "phase_order": 1,
            "phase_name": "基础期",
            "phase_goal": "系统梳理知识点，建立知识框架，完成基础题型训练",
            "week_start": 1,
            "week_end": foundation_weeks,
            "focus_subjects": ["行测(全模块)", "申论(归纳概括+综合分析)"],
            "study_hours_per_day": _DEFAULT_DAILY_STUDY_HOURS["基础期"],
        },
        {
            "phase_order": 2,
            "phase_name": "强化期",
            "phase_goal": "专项突破薄弱模块，限时训练提升速度和正确率",
            "week_start": foundation_weeks + 1,
            "week_end": foundation_weeks + reinforcement_weeks,
            "focus_subjects": ["行测(错题重做+限时套题)", "申论(大作文+贯彻执行)"],
            "study_hours_per_day": _DEFAULT_DAILY_STUDY_HOURS["强化期"],
        },
        {
            "phase_order": 3,
            "phase_name": "冲刺期",
            "phase_goal": "全真模拟，查漏补缺，调整考试状态",
            "week_start": foundation_weeks + reinforcement_weeks + 1,
            "week_end": total_weeks,
            "focus_subjects": ["行测(全真模拟)", "申论(全真模拟)", "时政热点+常识冲刺"],
            "study_hours_per_day": _DEFAULT_DAILY_STUDY_HOURS["冲刺期"],
        },
    ]
    return phases


def build_subject_checklist(
    *,
    subjects: dict[str, Any],
    user_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build detailed checklist for each subject based on user profile weaknesses."""
    result: dict[str, Any] = {}
    for name, info in subjects.items():
        modules = info.get("modules", {})
        items: list[str] = []
        resources: list[str] = []
        for module_name, subtopics in modules.items():
            for topic in subtopics:
                items.append(module_name + ": " + topic)
        result[name] = {
            "subject_name": name,
            "subject_category": info.get("category", name),
            "weight_percent": info.get("weight", 0),
            "checklist_items": items,
            "resources": [
                name + "历年真题汇编",
                name + "专项突破题库",
                name + "知识点思维导图",
            ],
        }
    return result


def format_study_plan_markdown(
    *,
    title: str,
    study_plan: dict[str, Any],
    phases: list[dict[str, Any]],
    subjects: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> str:
    """Render complete study plan as Markdown."""
    exam_date = study_plan.get("estimated_exam_date", "TBD")
    hours = study_plan.get("study_hours_per_day", 4)
    total_weeks = study_plan.get("total_weeks", 12)

    lines: list[str] = [
        "# " + str(title),
        "",
        "**考试时间**：" + str(exam_date) + "  ",
        "**每日学习时长**：" + str(hours) + " 小时  ",
        "**计划周期**：共 " + str(total_weeks) + " 周",
        "",
        "---",
        "",
        "## 阶段概览",
        "",
    ]

    for phase in phases:
        lines.append(
            "### " + str(phase.get("phase_name", "")) + "（第" + str(phase.get("week_start", "")) + "-" + str(phase.get("week_end", "")) + "周）"
        )
        lines.append("> " + str(phase.get("phase_goal", "")))
        lines.append("- 每日学习：" + str(phase.get("study_hours_per_day", 4)) + " 小时")
        lines.append("- 重点科目：" + "、".join(phase.get("focus_subjects", [])))
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 学习清单",
        "",
    ])

    for name, info in subjects.items():
        cat = info.get("subject_category", name)
        weight = info.get("weight_percent", 0)
        lines.append("### " + str(name) + "（" + str(cat) + "） - 权重 " + str(weight) + "%")
        for item in info.get("checklist_items", []):
            lines.append("- [ ] " + str(item))
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 每日任务（第1周示例）",
        "",
        "| 日期 | 科目 | 任务 | 时长 |",
        "|------|------|------|------|",
    ])

    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for task in tasks[:14]:
        dow_idx = min(task.get("day_of_week", 1) - 1, 6)
        dow = weekday_names[dow_idx]
        lines.append(
            "| W" + str(task.get("week_number", 1)) + " " + dow + " | "
            + str(task.get("subject", "")) + " | "
            + str(task.get("task_title", "")) + " | "
            + str(task.get("estimated_minutes", 60)) + "min |"
        )

    lines.extend([
        "",
        "---",
        "",
        "> 本计划由 GwyPilot 自动生成，可根据实际情况调整。祝你备考顺利！",
    ])

    return chr(10).join(lines)

