from __future__ import annotations

from app.gwy.agents.report_generator_agent import ReportGeneratorAgent


def test_report_generator_agent_produces_outline_and_report() -> None:
    agent = ReportGeneratorAgent()
    result = agent.run(
        title="宀椾綅鎺ㄨ崘鎶ュ憡",
        recommendations=[
            {
                "department_name": "北京市人社局",
                "office_name": "规划处",
                "job_title": "综合管理岗",
                "position_code": "BJ-001",
                "work_location": "北京",
                "education_requirement": "本科",
                "degree_requirement": "学士",
                "major_requirement": "计算机类",
                "score": 91,
                "risk_level": "low",
                "recommend_level": "strong_match",
                "need_manual_confirm": False,
                "reasons": [{"text": "专业条件匹配"}],
                "risks": [],
            },
            {
                "department_name": "北京市税务局",
                "office_name": "征管处",
                "job_title": "综合岗位",
                "position_code": "BJ-002",
                "work_location": "北京",
                "education_requirement": "本科",
                "degree_requirement": "学士",
                "major_requirement": "不限",
                "score": 79,
                "risk_level": "medium",
                "recommend_level": "good_match",
                "need_manual_confirm": True,
                "reasons": [{"text": "地区偏好匹配"}],
                "risks": [{"text": "需要复核备注"}],
            },
        ],
        risk_review={"risk_level": "medium", "risk_items": []},
    )

    assert result["outline"]
    assert result["report"]
    assert result["trace"][0]["step"] == "plan"
    assert "岗位逐条分析" in result["report"]
    assert "最终推荐" in result["report"]
    assert result["report_meta"]["used_llm"] is False
