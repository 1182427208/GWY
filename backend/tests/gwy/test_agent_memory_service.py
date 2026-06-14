"""Tests for AgentMemoryService and LongTermMemoryService."""

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


def test_build_memory_prompt_prioritizes_profile_fields() -> None:
    with _make_session() as session:
        user_id = uuid4()
        session.add(
            GwyUserProfile(
                user_id=user_id,
                political_status="中共党员",
                major="法学",
                education="本科",
                degree="学士",
            )
        )
        session.commit()

        svc = AgentMemoryService(session=session, user_id=user_id, conversation_id="conv-1")
        prompt = svc.build_memory_prompt()

        assert "用户基础资料" in prompt
        assert prompt.index("政治面貌") < prompt.index("专业")
        assert prompt.index("专业") < prompt.index("学历")
        assert "仅供参考，遇到冲突时以用户最新说明为准" in prompt


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

        extracted = service.extract_preferences_from_message("不对，我叫张佳慧")
        updated = long_term.auto_enrich_user_profile(
            user_id=user_id,
            extracted_fields=extracted,
        )

        assert updated["name"] == "张佳慧"
        profile = session.exec(select(GwyUserProfile).where(GwyUserProfile.user_id == user_id)).first()
        assert profile is not None
        assert profile.name == "张佳慧"


def test_build_cross_session_summary_orders_profile_context() -> None:
    with _make_session() as session:
        user_id = uuid4()
        session.add(
            GwyUserProfile(
                user_id=user_id,
                political_status="中共党员",
                major="计算机技术",
                education="硕士",
                degree="硕士",
            )
        )
        session.commit()

        svc = LongTermMemoryService(session=session)
        summary = svc.build_cross_session_summary(user_id=user_id)

        assert summary["user_profile"]["political_status"] == "中共党员"
        assert summary["user_profile"]["major"] == "计算机技术"
        assert summary["user_profile"]["education"] == "硕士"
        assert summary["user_profile"]["degree"] == "硕士"
