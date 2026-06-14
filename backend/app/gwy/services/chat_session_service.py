from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.config import settings
from app.gwy.models import (
    GwyChatAttachment,
    GwyChatMessage,
    GwyChatSession,
    GwyConversationMemory,
    GwyDecisionMemory,
    GwyRagCacheEntry,
    GwyUserProfile,
)
from app.gwy.services.agent_memory_service import AgentMemoryService
from app.gwy.services.long_term_memory_service import LongTermMemoryService

logger = logging.getLogger(__name__)


def _looks_like_invalid_identity_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if text in {
        "什么名字",
        "名字",
        "姓名",
        "昵称",
        "unknown",
        "null",
        "none",
        "n/a",
        "na",
    }:
        return True
    if any(token in lowered for token in {"名字", "姓名", "昵称", "name", "nick"}):
        return True
    if any(ch in text for ch in "?？=：:"):
        return True
    return len(text) < 2


class ChatSessionService:
    def __init__(self, session: Session, redis_client: Any | None = None) -> None:
        self.session = session
        self.redis_client = redis_client or self._build_redis_client()

    def create_session(self, user_id: UUID, title: str | None = None) -> GwyChatSession:
        chat_session = GwyChatSession(
            user_id=user_id,
            title=title or "新会话",
        )
        self.session.add(chat_session)
        self.session.commit()
        self.session.refresh(chat_session)
        return chat_session

    def list_sessions(self, user_id: UUID) -> list[GwyChatSession]:
        statement = (
            select(GwyChatSession)
            .where(GwyChatSession.user_id == user_id)
            .order_by(GwyChatSession.created_at.desc())
        )
        return list(self.session.exec(statement).all())

    def get_session(self, session_id: UUID, user_id: UUID) -> GwyChatSession:
        statement = select(GwyChatSession).where(
            GwyChatSession.id == session_id,
            GwyChatSession.user_id == user_id,
        )
        chat_session = self.session.exec(statement).first()
        if chat_session is None:
            raise LookupError("Chat session not found.")
        return chat_session

    def list_messages(self, session_id: UUID, user_id: UUID) -> list[GwyChatMessage]:
        self.get_session(session_id, user_id)
        statement = (
            select(GwyChatMessage)
            .where(GwyChatMessage.session_id == session_id)
            .order_by(GwyChatMessage.created_at.asc())
        )
        return list(self.session.exec(statement).all())

    def list_attachments(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> list[GwyChatAttachment]:
        self.get_session(session_id, user_id)
        statement = (
            select(GwyChatAttachment)
            .where(GwyChatAttachment.session_id == session_id)
            .order_by(GwyChatAttachment.created_at.asc())
        )
        return list(self.session.exec(statement).all())

    def list_active_attachments(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> list[GwyChatAttachment]:
        attachments = self.list_attachments(session_id, user_id)
        active_attachments: list[GwyChatAttachment] = []
        for attachment in attachments:
            metadata = dict(attachment.metadata_json or {})
            if bool(metadata.get("context_consumed")):
                continue
            active_attachments.append(attachment)
        return active_attachments

    def delete_attachment(
        self,
        session_id: UUID,
        user_id: UUID,
        attachment_id: UUID,
    ) -> None:
        self.get_session(session_id, user_id)
        statement = select(GwyChatAttachment).where(
            GwyChatAttachment.id == attachment_id,
            GwyChatAttachment.session_id == session_id,
        )
        attachment = self.session.exec(statement).first()
        if attachment is None:
            raise LookupError("Chat attachment not found.")

        file_path = Path(attachment.file_path) if attachment.file_path else None
        self.session.exec(
            delete(GwyChatAttachment).where(GwyChatAttachment.id == attachment_id)
        )
        self.session.commit()

        if file_path is not None:
            self._delete_attachment_files({file_path})

    def delete_session(self, session_id: UUID, user_id: UUID) -> None:
        self.get_session(session_id, user_id)
        attachments = self.list_attachments(session_id, user_id)
        file_paths = {
            Path(attachment.file_path)
            for attachment in attachments
            if attachment.file_path
        }

        cache_entries = list(
            self.session.exec(
                select(GwyRagCacheEntry).where(
                    GwyRagCacheEntry.session_id == session_id
                )
            ).all()
        )
        cache_keys = [
            self._cache_key(entry.query_hash)
            for entry in cache_entries
            if entry.query_hash
        ]

        self.session.exec(
            delete(GwyChatAttachment).where(GwyChatAttachment.session_id == session_id)
        )
        self.session.exec(
            delete(GwyChatMessage).where(GwyChatMessage.session_id == session_id)
        )
        self.session.exec(
            delete(GwyConversationMemory).where(
                GwyConversationMemory.conversation_id == str(session_id)
            )
        )
        self.session.exec(
            delete(GwyRagCacheEntry).where(GwyRagCacheEntry.session_id == session_id)
        )
        self.session.exec(delete(GwyChatSession).where(GwyChatSession.id == session_id))
        self.session.commit()

        self._delete_redis_cache_keys(cache_keys)
        self._delete_attachment_files(file_paths)

    def consume_attachments(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> None:
        attachments = self.list_active_attachments(session_id, user_id)
        if not attachments:
            return

        consumed_at = datetime.now(timezone.utc).isoformat()
        for attachment in attachments:
            metadata = dict(attachment.metadata_json or {})
            metadata["context_consumed"] = True
            metadata["context_consumed_at"] = consumed_at
            attachment.metadata_json = metadata
            self.session.add(attachment)
        self.session.commit()

    def add_attachment(
        self,
        *,
        session_id: UUID,
        file_name: str,
        original_name: str,
        attachment_type: str,
        mime_type: str,
        file_path: str,
        size_bytes: int = 0,
        summary: str | None = None,
        extracted_text: str | None = None,
        extraction_status: str = "uploaded",
        metadata_json: dict[str, Any] | None = None,
    ) -> GwyChatAttachment:
        attachment = GwyChatAttachment(
            session_id=session_id,
            file_name=file_name,
            original_name=original_name,
            attachment_type=attachment_type,
            mime_type=mime_type,
            file_path=file_path,
            size_bytes=size_bytes,
            summary=summary,
            extracted_text=extracted_text,
            extraction_status=extraction_status,
            metadata_json=metadata_json or {},
        )
        self.session.add(attachment)
        self.session.commit()
        self.session.refresh(attachment)
        return attachment

    def append_message(
        self,
        *,
        session_id: UUID,
        role: str,
        content: str,
        intent: str | None = None,
        historical_reference: bool = False,
        citations: list[dict[str, Any]] | None = None,
        retrieval_trace: list[dict[str, Any]] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> GwyChatMessage:
        message = GwyChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            intent=intent,
            historical_reference=historical_reference,
            citations=citations or [],
            retrieval_trace=retrieval_trace or [],
            metadata_json=metadata_json or {},
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)

        # Auto-extract user preferences from user messages
        if role == "user" and content:
            try:
                # Look up session to get user_id for cross-session memory
                chat_session = self.session.get(GwyChatSession, session_id)
                uid = chat_session.user_id if chat_session else None
                memory_service = AgentMemoryService(
                    session=self.session,
                    user_id=uid,
                    conversation_id=str(session_id),
                )
                extracted = memory_service.extract_preferences_from_message(content)
                if uid is not None and extracted:
                    long_term_service = LongTermMemoryService(
                        session=self.session,
                        redis_client=self.redis_client,
                    )
                    long_term_service.auto_enrich_user_profile(
                        user_id=uid,
                        extracted_fields=extracted,
                    )
            except Exception:
                logger.debug("Failed to extract preferences from message", exc_info=True)

        return message

    def update_session_state(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        title: str | None = None,
        summary: str | None = None,
        last_intent: str | None = None,
        active_topic: str | None = None,
        mentioned_docs: list[str] | None = None,
    ) -> GwyChatSession:
        chat_session = self.get_session(session_id, user_id)
        if title:
            chat_session.title = title
        if summary is not None:
            chat_session.summary = summary
            chat_session.summary_updated_at = datetime.now(timezone.utc)
        if last_intent is not None:
            chat_session.last_intent = last_intent
        if active_topic is not None:
            chat_session.active_topic = active_topic
        if mentioned_docs is not None:
            chat_session.mentioned_docs = mentioned_docs
        self.session.add(chat_session)
        self.session.commit()
        self._upsert_memory(
            user_id=user_id,
            conversation_id=str(session_id),
            memory_key="summary",
            memory_value={"summary": chat_session.summary or ""},
        )
        self._upsert_memory(
            user_id=user_id,
            conversation_id=str(session_id),
            memory_key="last_intent",
            memory_value={"last_intent": chat_session.last_intent},
        )
        self._upsert_memory(
            user_id=user_id,
            conversation_id=str(session_id),
            memory_key="active_topic",
            memory_value={"active_topic": chat_session.active_topic},
        )
        self._upsert_memory(
            user_id=user_id,
            conversation_id=str(session_id),
            memory_key="mentioned_docs",
            memory_value={"mentioned_docs": chat_session.mentioned_docs},
        )
        return chat_session

    def get_memory_context(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        chat_session = self.get_session(session_id, user_id)
        messages = self.list_messages(session_id, user_id)
        recent_messages = messages[-(settings.RAG_MEMORY_TURNS * 2) :]
        conversation_memory = self._load_memory_snapshot(
            conversation_id=str(session_id),
            user_id=user_id,
        )
        # Build AgentMemoryService for short-term + long-term context
        memory_service = AgentMemoryService(
            session=self.session,
            redis_client=None,
            user_id=user_id,
            conversation_id=str(session_id),
        )
        long_term_service = LongTermMemoryService(
            session=self.session,
            redis_client=self.redis_client,
        )
        user_profile = long_term_service.build_user_profile_context(user_id=user_id)
        open_topics = self._build_open_topics(chat_session, conversation_memory, recent_messages)
        return {
            "session_summary": chat_session.summary
            or self.build_session_summary(messages),
            "last_intent": chat_session.last_intent,
            "active_topic": chat_session.active_topic,
            "open_topics": open_topics,
            "mentioned_docs": list(chat_session.mentioned_docs or []),
            "recent_messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in recent_messages
            ],
            "conversation_memory": conversation_memory,
            "extracted_preferences": memory_service.get_extracted_preferences(),
            "long_term_context": long_term_service.build_cross_session_summary(
                user_id=user_id
            ),
            "user_profile": user_profile,
            "memory_prompt": memory_service.build_memory_prompt(),
        }

    def build_session_summary(self, messages: list[GwyChatMessage]) -> str:
        recent_messages = messages[-(settings.RAG_MEMORY_TURNS * 2) :]
        lines: list[str] = []
        for message in recent_messages:
            role = "用户" if message.role == "user" else "助手"
            snippet = message.content.strip().replace("\n", " ")
            if len(snippet) > 120:
                snippet = f"{snippet[:117]}..."
            lines.append(f"{role}：{snippet}")
        summary = "；".join(lines)
        return summary[: settings.WORKING_MEMORY_SUMMARY_MAX_CHARS]

    def get_cached_response(
        self,
        *,
        session_id: UUID | None,
        query_hash: str,
    ) -> dict[str, Any] | None:
        cache_key = self._cache_key(query_hash)
        if self.redis_client is not None:
            raw = self.redis_client.get(cache_key)
            if raw:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("Failed to decode Redis cache payload.", exc_info=True)

        statement = select(GwyRagCacheEntry).where(
            GwyRagCacheEntry.query_hash == query_hash
        )
        cache_entry = self.session.exec(statement).first()
        if cache_entry is None:
            return None
        return cache_entry.response_json

    def set_cached_response(
        self,
        *,
        session_id: UUID | None,
        query_hash: str,
        request_json: dict[str, Any],
        response_json: dict[str, Any],
    ) -> None:
        payload = json.dumps(response_json, ensure_ascii=False)
        cache_key = self._cache_key(query_hash)

        if self.redis_client is not None:
            try:
                self.redis_client.set(cache_key, payload)
            except Exception:  # pragma: no cover - Redis best-effort
                logger.debug("Failed to write Redis cache.", exc_info=True)

        statement = select(GwyRagCacheEntry).where(
            GwyRagCacheEntry.query_hash == query_hash
        )
        cache_entry = self.session.exec(statement).first()
        if cache_entry is None:
            cache_entry = GwyRagCacheEntry(
                session_id=session_id,
                query_hash=query_hash,
                request_json=request_json,
                response_json=response_json,
                expires_at=None,
            )
        else:
            cache_entry.session_id = session_id
            cache_entry.request_json = request_json
            cache_entry.response_json = response_json
            cache_entry.expires_at = None
        self.session.add(cache_entry)
        self.session.commit()

    def record_decision(
        self,
        *,
        user_id: UUID,
        position_id: UUID | None = None,
        decision_type: str,
        decision_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        memory = GwyDecisionMemory(
            user_id=user_id,
            position_id=position_id,
            decision_type=decision_type,
            decision_reason=decision_reason,
            metadata_json=dict(metadata or {}),
        )
        self.session.add(memory)
        self.session.commit()

    def _upsert_memory(
        self,
        *,
        user_id: UUID | None,
        conversation_id: str,
        memory_key: str,
        memory_value: dict[str, Any],
    ) -> None:
        statement = select(GwyConversationMemory).where(
            GwyConversationMemory.conversation_id == conversation_id,
            GwyConversationMemory.memory_key == memory_key,
        )
        if user_id is not None:
            statement = statement.where(GwyConversationMemory.user_id == user_id)
        memory = self.session.exec(statement).first()
        if memory is None:
            memory = GwyConversationMemory(
                user_id=user_id,
                conversation_id=conversation_id,
                memory_key=memory_key,
                memory_value=memory_value,
                expires_at=None,
            )
        else:
            memory.user_id = user_id
            memory.memory_value = memory_value
            memory.expires_at = None
        self.session.add(memory)
        self.session.commit()

    def _load_memory_snapshot(
        self,
        *,
        conversation_id: str,
        user_id: UUID | None,
    ) -> dict[str, dict[str, Any]]:
        statement = select(GwyConversationMemory).where(
            GwyConversationMemory.conversation_id == conversation_id
        )
        if user_id is not None:
            statement = statement.where(GwyConversationMemory.user_id == user_id)
        memories = self.session.exec(statement).all()
        snapshot: dict[str, dict[str, Any]] = {}
        for memory in memories:
            snapshot[memory.memory_key] = dict(memory.memory_value or {})
        return snapshot

    def _build_open_topics(
        self,
        chat_session: GwyChatSession,
        conversation_memory: dict[str, dict[str, Any]],
        recent_messages: list[GwyChatMessage],
    ) -> list[str]:
        topics: list[str] = []
        active_topic = (chat_session.active_topic or "").strip()
        if active_topic:
            topics.append(active_topic)
        summary_topic = (conversation_memory.get("summary") or {}).get("summary", "").strip()
        if summary_topic and summary_topic not in topics:
            topics.append(summary_topic)
        mentioned_docs = list(chat_session.mentioned_docs or [])
        for doc in mentioned_docs:
            text = str(doc).strip()
            if text and text not in topics:
                topics.append(text)
        for message in recent_messages[-4:]:
            snippet = message.content.strip().replace("\n", " ")
            if len(snippet) > 48:
                snippet = f"{snippet[:45]}..."
            if snippet and snippet not in topics:
                topics.append(snippet)
        return topics[: settings.WORKING_MEMORY_OPEN_TOPICS_LIMIT]

    def _build_redis_client(self) -> Any | None:
        if not settings.REDIS_URL:
            return None
        try:
            import redis

            client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
            client.ping()
            return client
        except Exception:  # pragma: no cover - Redis best-effort
            logger.debug(
                "Redis unavailable, falling back to PostgreSQL cache.",
                exc_info=True,
            )
            return None

    def _cache_key(self, query_hash: str) -> str:
        return f"gwy:rag:{query_hash}"

    def _delete_redis_cache_keys(self, cache_keys: list[str]) -> None:
        if self.redis_client is None or not cache_keys:
            return
        try:
            self.redis_client.delete(*cache_keys)
        except Exception:  # pragma: no cover - Redis best-effort
            logger.debug("Failed to delete Redis cache keys.", exc_info=True)

    def _delete_attachment_files(self, file_paths: set[Path]) -> None:
        if not file_paths:
            return

        upload_root = Path(__file__).resolve().parents[4] / "data" / "processed" / "chat_uploads"
        for file_path in file_paths:
            try:
                if file_path.exists():
                    file_path.unlink()
                parent_dir = file_path.parent
                if parent_dir.exists() and upload_root in parent_dir.parents:
                    if not any(parent_dir.iterdir()):
                        parent_dir.rmdir()
            except Exception:  # pragma: no cover - filesystem best-effort
                logger.debug(
                    "Failed to delete chat attachment file: %s",
                    file_path,
                    exc_info=True,
                )
