from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import settings
from app.gwy.models import (
    GwyChatAttachment,
    GwyChatMessage,
    GwyChatSession,
    GwyConversationMemory,
    GwyRagCacheEntry,
    GwyUserProfile,
)
from app.gwy.services.chat_session_service import ChatSessionService
from app.models import User


class FakeRedis:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, *keys: str) -> int:
        self.deleted_keys.extend(keys)
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


def test_delete_session_cleans_db_rows_files_and_cache(
    db: Session,
    normal_user_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    fake_redis = FakeRedis()
    service = ChatSessionService(db, redis_client=fake_redis)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    session = service.create_session(user_id=user.id)
    session_id = session.id

    service.append_message(session_id=session_id, role="user", content="你好")

    session_upload_dir = tmp_path / "chat_uploads" / str(session_id)
    session_upload_dir.mkdir(parents=True, exist_ok=True)
    attachment_path = session_upload_dir / "sample.txt"
    attachment_path.write_text("attachment", encoding="utf-8")
    service.add_attachment(
        session_id=session_id,
        file_name="sample.txt",
        original_name="sample.txt",
        attachment_type="other",
        mime_type="text/plain",
        file_path=str(attachment_path),
        size_bytes=attachment_path.stat().st_size,
    )

    db.add(
        GwyConversationMemory(
            user_id=session.user_id,
            conversation_id=str(session_id),
            memory_key="summary",
            memory_value={"summary": "cached"},
        )
    )
    db.commit()

    query_hash = "delete-session-cache"
    service.set_cached_response(
        session_id=session_id,
        query_hash=query_hash,
        request_json={"query": "你好"},
        response_json={"answer": "cached"},
    )
    assert f"gwy:rag:{query_hash}" in fake_redis.values
    cached = service.get_cached_response(session_id=session_id, query_hash=query_hash)
    assert cached == {"answer": "cached"}

    service.delete_session(session_id, user.id)

    assert db.get(GwyChatSession, session_id) is None
    assert db.exec(select(GwyChatMessage).where(GwyChatMessage.session_id == session_id)).all() == []
    assert db.exec(select(GwyChatAttachment).where(GwyChatAttachment.session_id == session_id)).all() == []
    assert (
        db.exec(
            select(GwyConversationMemory).where(
                GwyConversationMemory.conversation_id == str(session_id)
            )
        ).all()
        == []
    )
    assert db.exec(select(GwyRagCacheEntry).where(GwyRagCacheEntry.session_id == session_id)).all() == []
    assert attachment_path.exists() is False
    assert f"gwy:rag:{query_hash}" in fake_redis.deleted_keys


def test_cached_response_survives_expired_timestamp(db: Session) -> None:
    service = ChatSessionService(db, redis_client=None)
    cache_entry = GwyRagCacheEntry(
        session_id=None,
        query_hash="expired-cache",
        request_json={"query": "你好"},
        response_json={"answer": "still here"},
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(cache_entry)
    db.commit()

    cached = service.get_cached_response(session_id=None, query_hash="expired-cache")
    assert cached == {"answer": "still here"}


def test_memory_context_includes_working_memory_and_user_profile(
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    service = ChatSessionService(db, redis_client=None)
    session = service.create_session(user_id=user.id)

    db.add(
        GwyUserProfile(
            user_id=user.id,
            major="法学",
            education="本科",
            political_status="中共党员",
        )
    )
    db.commit()

    service.update_session_state(
        session_id=session.id,
        user_id=user.id,
        summary="用户在问岗位推荐和地区偏好",
        last_intent="岗位推荐",
        active_topic="地区筛选",
        mentioned_docs=["报名指南", "专业目录"],
    )

    for idx in range(settings.RAG_MEMORY_TURNS * 2 + 4):
        service.append_message(
            session_id=session.id,
            role="user" if idx % 2 == 0 else "assistant",
            content=f"消息 {idx}",
        )

    context = service.get_memory_context(session_id=session.id, user_id=user.id)

    assert len(context["recent_messages"]) == settings.RAG_MEMORY_TURNS * 2
    assert context["user_profile"]["major"] == "法学"
    assert context["user_profile"]["political_status"] == "中共党员"
    assert isinstance(context["open_topics"], list)
    assert len(context["open_topics"]) <= settings.WORKING_MEMORY_OPEN_TOPICS_LIMIT
    assert len(context["session_summary"]) <= settings.WORKING_MEMORY_SUMMARY_MAX_CHARS


def test_memory_context_filters_invalid_identity_values(
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    service = ChatSessionService(db, redis_client=None)
    session = service.create_session(user_id=user.id)

    db.add(
        GwyUserProfile(
            user_id=user.id,
            name="什么名字",
            nickname="昵称",
            major="法学",
        )
    )
    db.commit()

    context = service.get_memory_context(session_id=session.id, user_id=user.id)

    assert context["user_profile"]["name"] is None
    assert context["user_profile"]["nickname"] is None
    assert context["user_profile"]["major"] == "法学"
