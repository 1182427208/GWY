from __future__ import annotations

from app.gwy.agents.risk_review_agent import RiskReviewAgent


def test_risk_review_agent_returns_structured_risk_items() -> None:
    agent = RiskReviewAgent()
    result = agent.run(
        query="请帮我审查这个岗位是否存在风险",
        recommendations=[
            {
                "position_id": "pos-1",
                "job_title": "行政执法岗",
                "remarks": "需基层工作经历2年，面试可能有专业测试",
                "score": 82,
            }
        ],
    )

    assert result["risk_level"] in {"low", "medium", "high"}
    assert result["risk_items"]
    assert result["trace"][0]["step"] == "risk_intent_analysis"
    assert any(item["risk_type"] == "service_year_limit" for item in result["risk_items"])
    assert any(item["risk_type"] == "professional_test" for item in result["risk_items"])
