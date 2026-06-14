from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session, SQLModel, create_engine, select

from app.gwy.models import GwyUserProfile
from app.gwy.services.long_term_memory_service import LongTermMemoryService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted_keys: list[str] = []

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:  # noqa: ARG002
        self.values[key] = value

    def delete(self, *keys: str) -> int:
        self.deleted_keys.extend(keys)
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_long_term_summary_uses_redis_cache_when_available() -> None:
    with _make_session() as session:
        user_id = uuid4()
        session.add(
            GwyUserProfile(
                user_id=user_id,
                name="张佳慧",
                nickname="佳慧",
                major="法学",
                political_status="中共党员",
            )
        )
        session.commit()

        fake_redis = FakeRedis()
        svc = LongTermMemoryService(session=session, redis_client=fake_redis)

        first = svc.build_cross_session_summary(user_id=user_id)
        assert first["user_profile"]["name"] == "张佳慧"
        assert fake_redis.values

        profile = session.exec(
            select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        ).first()
        assert profile is not None
        session.delete(profile)
        session.commit()

        second = svc.build_cross_session_summary(user_id=user_id)
        assert second["user_profile"]["name"] == "张佳慧"
        assert second["user_profile"]["nickname"] == "佳慧"


def test_long_term_cache_is_invalidated_after_profile_update() -> None:
    with _make_session() as session:
        user_id = uuid4()
        session.add(GwyUserProfile(user_id=user_id, major="法学"))
        session.commit()

        fake_redis = FakeRedis()
        svc = LongTermMemoryService(session=session, redis_client=fake_redis)

        svc.build_cross_session_summary(user_id=user_id)
        assert fake_redis.values

        svc.auto_enrich_user_profile(
            user_id=user_id,
            extracted_fields={"name": "张佳慧", "nickname": "佳慧"},
        )

        assert not fake_redis.values
