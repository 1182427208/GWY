from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session, SQLModel, create_engine, select

from app.gwy.models import GwyUserProfile
from app.gwy.services.agent_memory_service import AgentMemoryService
from app.gwy.services.long_term_memory_service import LongTermMemoryService


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_question_about_name_does_not_overwrite_profile() -> None:
    with _make_session() as session:
        user_id = uuid4()
        service = AgentMemoryService(
            session=session,
            user_id=user_id,
            conversation_id="conv-1",
        )
        long_term = LongTermMemoryService(session=session)

        extracted = service.extract_preferences_from_message("我的名字是什么？")
        assert "name" not in extracted
        assert "nickname" not in extracted

        updated = long_term.auto_enrich_user_profile(
            user_id=user_id,
            extracted_fields=extracted,
        )
        assert updated == {}

        profile = session.exec(
            select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        ).first()
        assert profile is None


def test_name_correction_overwrites_previous_value() -> None:
    with _make_session() as session:
        user_id = uuid4()
        session.add(GwyUserProfile(user_id=user_id, name="什么名字"))
        session.commit()

        service = AgentMemoryService(
            session=session,
            user_id=user_id,
            conversation_id="conv-2",
        )
        long_term = LongTermMemoryService(session=session)

        extracted = service.extract_preferences_from_message("不对，应该记录我叫张佳慧")
        assert extracted["name"] == "张佳慧"

        updated = long_term.auto_enrich_user_profile(
            user_id=user_id,
            extracted_fields=extracted,
        )
        assert updated["name"] == "张佳慧"

        profile = session.exec(
            select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)
        ).first()
        assert profile is not None
        assert profile.name == "张佳慧"


def test_invalid_profile_name_is_not_rendered_into_memory_prompt() -> None:
    with _make_session() as session:
        user_id = uuid4()
        session.add(
            GwyUserProfile(
                user_id=user_id,
                name="什么名字",
                major="计算机技术",
                political_status="中共党员",
            )
        )
        session.commit()

        service = AgentMemoryService(
            session=session,
            user_id=user_id,
            conversation_id="conv-3",
        )

        prompt = service.build_memory_prompt()
        assert "什么名字" not in prompt
        assert "姓名" not in prompt
        assert "专业" in prompt
