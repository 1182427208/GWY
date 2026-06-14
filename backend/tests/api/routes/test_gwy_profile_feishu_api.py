from __future__ import annotations

from sqlmodel import Session, select

from app.api.routes import gwy as gwy_routes
from app.core.config import settings
from app.gwy.models import GwyUserProfile
from app.models import User


def test_profile_api_exposes_feishu_webhook_field(
    client,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    response = client.get(
        f"{settings.API_V1_STR}/gwy/profile/me",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["feishu_webhook_url"] is None


def test_profile_api_updates_feishu_webhook_field(
    client,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    payload = {
        "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
    }

    response = client.put(
        f"{settings.API_V1_STR}/gwy/profile/me",
        headers=normal_user_token_headers,
        json=payload,
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["feishu_webhook_url"] == payload["feishu_webhook_url"]

    saved = db.exec(
        select(GwyUserProfile).where(GwyUserProfile.user_id == user.id)
    ).first()
    assert saved is not None
    assert saved.feishu_webhook_url == payload["feishu_webhook_url"]


def test_feishu_webhook_test_uses_request_webhook_and_pushes_message(
    client,
    normal_user_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    calls: dict[str, object] = {}

    class FakeFeishuPushAgent:
        def run(self, **kwargs: object) -> dict[str, object]:
            calls.update(kwargs)
            return {
                "status": "sent",
                "error_message": None,
                "response_json": {"code": 0, "msg": "ok"},
                "trace": [
                    {"step": "plan", "status": "done"},
                    {"step": "push", "status": "done"},
                    {"step": "reflect", "status": "sent"},
                ],
            }

    monkeypatch.setattr(gwy_routes, "FeishuPushAgent", FakeFeishuPushAgent)

    response = client.post(
        f"{settings.API_V1_STR}/gwy/profile/me/feishu/test",
        headers=normal_user_token_headers,
        json={
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "sent"
    assert payload["detail"] == "Feishu webhook test succeeded."
    assert calls["webhook_url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    assert calls["report_kind"] == "analysis"
    assert "连接测试" in str(calls["title"])


def test_feishu_webhook_test_requires_webhook(
    client,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    profile = db.exec(
        select(GwyUserProfile).where(GwyUserProfile.user_id == user.id)
    ).first()
    if profile is not None:
        profile.feishu_webhook_url = None
        db.add(profile)
        db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/gwy/profile/me/feishu/test",
        headers=normal_user_token_headers,
        json={},
    )

    assert response.status_code == 400
    assert "Feishu webhook URL" in response.json()["detail"]
