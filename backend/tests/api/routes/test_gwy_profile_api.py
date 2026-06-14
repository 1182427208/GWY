from __future__ import annotations

from sqlmodel import Session, select

from app.api.routes import gwy as gwy_routes
from app.core.config import settings
from app.gwy.models import GwyUserProfile
from app.models import User


def test_profile_api_returns_blank_profile_for_current_user(
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
    assert payload["user_id"] == str(user.id)
    assert payload["education"] is None
    assert payload["target_regions"] == []

    profile = db.exec(
        select(GwyUserProfile).where(GwyUserProfile.user_id == user.id)
    ).first()
    assert profile is not None


def test_profile_api_updates_and_persists_profile(
    client,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    payload = {
        "education": "本科",
        "degree": "学士",
        "major": "法学",
        "political_status": "中共党员",
        "is_fresh_graduate": False,
        "grassroots_experience_years": 0,
        "target_regions": ["北京"],
        "avoid_conditions": ["基层岗位"],
        "desired_departments": ["税务系统"],
        "desired_positions": ["综合管理"],
        "excluded_positions": ["值班岗位"],
        "daily_study_hours": 3,
        "notes": "优先北京",
    }

    response = client.put(
        f"{settings.API_V1_STR}/gwy/profile/me",
        headers=normal_user_token_headers,
        json=payload,
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["major"] == "法学"
    assert updated["target_regions"] == ["北京"]
    assert updated["avoid_conditions"] == ["基层岗位"]
    assert updated["daily_study_hours"] == 3

    saved = db.exec(
        select(GwyUserProfile).where(GwyUserProfile.user_id == user.id)
    ).first()
    assert saved is not None
    assert saved.major == "法学"
    assert saved.target_regions == ["北京"]
    assert saved.avoid_conditions == ["基层岗位"]
    assert saved.daily_study_hours == 3

    get_response = client.get(
        f"{settings.API_V1_STR}/gwy/profile/me",
        headers=normal_user_token_headers,
    )
    assert get_response.status_code == 200
    assert get_response.json()["major"] == "法学"

