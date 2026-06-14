from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.routes import gwy as gwy_routes
from app.core.config import settings


class RecordingPolicyRagService:
    last_kwargs: dict[str, object] | None = None

    def __init__(self, session: Session | None = None, **_: object) -> None:
        self.session = session

    def query_policy(self, **kwargs: object) -> dict[str, object]:
        RecordingPolicyRagService.last_kwargs = dict(kwargs)
        return {
            "answer": "已进入岗位推荐",
            "intent": "position_recommendation",
            "need_rag": False,
            "decision_branch": "postgresql_position_recommendation",
            "citations": [],
            "retrieval_trace": [{"step": "intent_routing"}],
            "rewritten_queries": [],
            "metadata_filter": None,
            "rerank_results": [],
            "recommendations": [],
            "need_more_info": False,
            "missing_fields": [],
            "recommendation_task_id": None,
            "historical_reference": False,
        }


def test_policy_query_api_passes_explicit_position_mode(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(gwy_routes, "PolicyRagService", RecordingPolicyRagService)

    response = client.post(
        f"{settings.API_V1_STR}/gwy/policy/query",
        json={
            "query": "please match jobs",
            "year": 2026,
            "exam_type": "national",
            "mode": "position_recommendation",
            "intent_hint": "position_recommendation",
            "position_profile": {
                "major": "法学",
                "education": "本科",
                "degree": "学士",
                "political_status": "中共党员",
                "target_regions": ["北京"],
            },
            "top_k": 5,
            "use_rerank": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "position_recommendation"
    assert payload["decision_branch"] == "postgresql_position_recommendation"

    passed_kwargs = RecordingPolicyRagService.last_kwargs or {}
    assert passed_kwargs["mode"] == "position_recommendation"
    assert passed_kwargs["intent_hint"] == "position_recommendation"
    position_profile = passed_kwargs["position_profile"]
    assert isinstance(position_profile, dict)
    assert position_profile["major"] == "法学"
    assert position_profile["target_regions"] == ["北京"]
