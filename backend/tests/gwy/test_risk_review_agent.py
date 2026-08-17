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


def test_risk_review_agent_deduplicates_same_position_and_risk_type() -> None:
    result = RiskReviewAgent().run(
        query="risk",
        recommendations=[
            {
                "position_id": "pos-1",
                "job_title": "Position A",
                "remarks": "基层经历要求，基层经历要求",
            }
        ],
    )

    service_year_items = [
        item for item in result["risk_items"] if item["risk_type"] == "service_year_limit"
    ]
    assert len(service_year_items) == 1
    assert service_year_items[0]["position_id"] == "pos-1"
    assert service_year_items[0]["verification_task"]
