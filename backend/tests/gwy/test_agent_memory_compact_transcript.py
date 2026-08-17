from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session, SQLModel, create_engine, select

from app.gwy.models import GwyConversationMemory
from app.gwy.services.agent_memory_service import AgentMemoryService


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_save_compact_transcript_persists_to_conversation_memory() -> None:
    with _make_session() as session:
        user_id = uuid4()
        service = AgentMemoryService(
            session=session,
            user_id=user_id,
            conversation_id="conv-compact",
        )

        record = service.save_compact_transcript(
            [{"role": "user", "content": "hello"}],
            focus="keep facts",
        )
        service.save_compact_summary(
            "summary text",
            transcript_id=record["transcript_id"],
            focus="keep facts",
        )

        transcript = session.exec(
            select(GwyConversationMemory).where(
                GwyConversationMemory.conversation_id == "conv-compact",
                GwyConversationMemory.memory_key
                == f"compact_transcript:{record['transcript_id']}",
            )
        ).first()
        summary = session.exec(
            select(GwyConversationMemory).where(
                GwyConversationMemory.conversation_id == "conv-compact",
                GwyConversationMemory.memory_key == "compact_summary",
            )
        ).first()

        assert transcript is not None
        assert transcript.memory_value["focus"] == "keep facts"
        assert transcript.memory_value["messages"] == [{"role": "user", "content": "hello"}]
        assert summary is not None
        assert summary.memory_value["summary"] == "summary text"
        assert summary.memory_value["transcript_id"] == record["transcript_id"]

