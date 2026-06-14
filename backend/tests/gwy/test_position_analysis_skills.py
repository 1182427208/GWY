from __future__ import annotations

from app.gwy.skills.position_analysis_skills import build_analysis_strategy


def test_build_analysis_strategy_prefers_explore_then_verify_when_history_is_sparse() -> None:
    strategy = build_analysis_strategy(
        {
            "report_title": "北京岗位分析报告",
            "analysis_goal": "结合历史趋势与政策证据生成岗位分析",
            "query": "北京 计算机类 岗位分析",
        },
        position_facts={
            "selected_positions": [
                {
                    "id": "pos-1",
                    "department_name": "北京市人社局",
                    "job_title": "综合管理岗",
                    "position_code": "BJ-001",
                    "history": {
                        "summary": {
                            "record_count": 0,
                            "latest_recruit_count": None,
                            "latest_interview_ratio": None,
                        },
                        "records": [],
                    },
                }
            ],
            "recommendations": [],
        },
        policy_evidence=[],
    )

    assert strategy["strategy_name"] == "explore_then_verify"
    assert strategy["planning_strategy"] == "plan_and_solve"
    assert strategy["evidence_strategy"] == "react"
    assert strategy["research_targets"][0]["needs_web_search"] is True
    assert "历史招录" in strategy["research_targets"][0]["focus"]


def test_build_analysis_strategy_prefers_history_first_when_history_is_rich() -> None:
    strategy = build_analysis_strategy(
        {
            "report_title": "北京岗位分析报告",
            "analysis_goal": "结合历史趋势与政策证据生成岗位分析",
            "query": "北京 计算机类 岗位分析",
        },
        position_facts={
            "selected_positions": [
                {
                    "id": "pos-1",
                    "department_name": "北京市人社局",
                    "job_title": "综合管理岗",
                    "position_code": "BJ-001",
                    "history": {
                        "summary": {
                            "record_count": 3,
                            "latest_recruit_count": 4,
                            "latest_interview_ratio": 0.15,
                            "recruit_count_trend": "downward",
                            "interview_ratio_trend": "upward",
                        },
                        "records": [
                            {"year": 2026, "recruit_count": 4, "interview_ratio": "1:6"},
                            {"year": 2025, "recruit_count": 5, "interview_ratio": "1:7"},
                            {"year": 2024, "recruit_count": 6, "interview_ratio": "1:8"},
                        ],
                    },
                }
            ],
            "recommendations": [],
        },
        policy_evidence=[{"doc_title": "招录公告", "content": "岗位公告原文"}],
    )

    assert strategy["strategy_name"] == "history_first"
    assert strategy["planning_strategy"] == "plan_and_solve"
    assert strategy["evidence_strategy"] == "react"
    assert strategy["research_targets"][0]["needs_web_search"] is False
    assert strategy["research_targets"][0]["history_priority"] == "high"
