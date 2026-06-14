from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import gwy as gwy_routes
from app.core.config import settings
from app.gwy.models import (
    GwyChatAttachment,
    GwyChatMessage,
    GwyChatSession,
    GwyConversationMemory,
    GwyRagCacheEntry,
)
from app.gwy.services.chat_session_service import ChatSessionService


class FakePolicyRagService:
    def __init__(self, session: Session | None = None, **_: object) -> None:
        self.session = session

    def query_policy(self, **kwargs: object) -> dict[str, object]:
        query = str(kwargs.get("query") or "")
        if "岗位" in query or "职位" in query:
            return {
                "answer": "我先帮你筛出 3 个更值得看的岗位。",
                "intent": "position_recommendation",
                "need_rag": False,
                "decision_branch": "postgresql_position_recommendation",
                "citations": [],
                "retrieval_trace": [{"step": "position_recommendation"}],
                "rewritten_queries": [],
                "metadata_filter": None,
                "rerank_results": [],
                "recommendations": [
                    {
                        "department_name": "国家税务总局北京税务局",
                        "job_title": "一级行政执法员",
                        "position_code": "001",
                        "score": 92.5,
                        "recommend_level": "strong_match",
                        "risk_level": "low",
                        "need_manual_confirm": False,
                        "reasons": [{"type": "major_match", "text": "专业条件匹配"}],
                        "risks": [],
                    }
                ],
                "need_more_info": False,
                "missing_fields": [],
                "recommendation_task_id": "task-1",
                "historical_reference": False,
            }
        return {
            "answer": "请在规定时间内登录系统打印准考证。",
            "intent": "admission_ticket",
            "need_rag": True,
            "citations": [
                {
                    "chunk_id": "chunk-1",
                    "content": "打印准考证说明",
                    "score": 0.93,
                    "rerank_score": 0.97,
                    "source_file": "data/考务问答/如何打印准考证.pdf",
                    "doc_title": "如何打印准考证",
                    "section": "准考证",
                    "page_start": 1,
                    "page_end": 1,
                    "metadata": {},
                }
            ],
            "retrieval_trace": [{"step": "citation_guard", "passed": True}],
            "rewritten_queries": ["如何打印准考证", "准考证打印时间"],
            "metadata_filter": 'year == 2026 and exam_type == "national"',
            "rerank_results": [
                {
                    "id": "chunk-1",
                    "content": "打印准考证说明",
                    "score": 0.93,
                    "rerank_score": 0.97,
                }
            ],
            "recommendations": [],
            "need_more_info": False,
            "missing_fields": [],
            "recommendation_task_id": None,
            "historical_reference": False,
        }

    def answer_chat_message(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        query: str,
        year: int = 2026,
        exam_type: str = "national",
        doc_group: str | None = None,
        doc_type: str | None = None,
        top_k: int = 6,
        use_rerank: bool = True,
        mode: str | None = None,
        intent_hint: str | None = None,
        position_profile: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = (
            year,
            exam_type,
            doc_group,
            doc_type,
            top_k,
            use_rerank,
            mode,
            intent_hint,
            position_profile,
        )
        chat_service = ChatSessionService(self.session)  # type: ignore[arg-type]
        user_message = chat_service.append_message(
            session_id=session_id,
            role="user",
            content=query,
        )
        result = self.query_policy(query=query)
        assistant_message = chat_service.append_message(
            session_id=session_id,
            role="assistant",
            content=str(result["answer"]),
            intent=str(result["intent"]),
            historical_reference=bool(result["historical_reference"]),
            citations=list(result["citations"]),
            retrieval_trace=list(result["retrieval_trace"]),
            metadata_json={
                "rewritten_queries": list(result["rewritten_queries"]),
                "metadata_filter": result["metadata_filter"],
                "rerank_results": list(result["rerank_results"]),
            },
        )
        session = chat_service.update_session_state(
            session_id=session_id,
            user_id=user_id,
            summary="用户：如何打印准考证；助手：请在规定时间内登录系统打印准考证。",
            last_intent=str(result["intent"]),
            active_topic="准考证",
            mentioned_docs=["如何打印准考证"],
        )
        return {
            **result,
            "session": {
                "id": str(session.id),
                "title": session.title,
                "last_intent": session.last_intent,
                "active_topic": session.active_topic,
                "mentioned_docs": list(session.mentioned_docs or []),
                "summary": session.summary,
                "created_at": session.created_at,
            },
            "user_message": {
                "id": str(user_message.id),
                "session_id": str(user_message.session_id),
                "role": user_message.role,
                "content": user_message.content,
                "intent": user_message.intent,
                "historical_reference": user_message.historical_reference,
                "citations": list(user_message.citations or []),
                "retrieval_trace": list(user_message.retrieval_trace or []),
                "metadata_json": dict(user_message.metadata_json or {}),
                "created_at": user_message.created_at,
            },
            "assistant_message": {
                "id": str(assistant_message.id),
                "session_id": str(assistant_message.session_id),
                "role": assistant_message.role,
                "content": assistant_message.content,
                "intent": assistant_message.intent,
                "historical_reference": assistant_message.historical_reference,
                "citations": list(assistant_message.citations or []),
                "retrieval_trace": list(assistant_message.retrieval_trace or []),
                "metadata_json": dict(assistant_message.metadata_json or {}),
                "created_at": assistant_message.created_at,
            },
        }


def test_policy_query_api_returns_rag_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gwy_routes, "PolicyRagService", FakePolicyRagService)

    response = client.post(
        f"{settings.API_V1_STR}/gwy/policy/query",
        json={
            "query": "如何打印准考证？",
            "year": 2026,
            "exam_type": "national",
            "doc_group": "exam_affairs_qa",
            "top_k": 5,
            "use_rerank": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("请在规定时间内")
    assert payload["intent"] == "admission_ticket"
    assert payload["need_rag"] is True
    assert len(payload["citations"]) == 1
    assert payload["metadata_filter"]
    assert payload["rerank_results"]
    assert payload["retrieval_trace"][0]["step"] == "citation_guard"


def test_policy_query_api_returns_position_recommendations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gwy_routes, "PolicyRagService", FakePolicyRagService)

    response = client.post(
        f"{settings.API_V1_STR}/gwy/policy/query",
        json={
            "query": "帮我推荐几个适合我的岗位",
            "year": 2026,
            "exam_type": "national",
            "top_k": 5,
            "use_rerank": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "position_recommendation"
    assert payload["need_rag"] is False
    assert payload["decision_branch"] == "postgresql_position_recommendation"
    assert payload["recommendations"][0]["position_code"] == "001"
    assert payload["need_more_info"] is False
    assert payload["recommendation_task_id"] == "task-1"


def test_chat_session_api_supports_multi_session(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gwy_routes, "PolicyRagService", FakePolicyRagService)

    create_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions",
        headers=normal_user_token_headers,
        json={"title": "准考证咨询"},
    )
    assert create_response.status_code == 200
    session_payload = create_response.json()
    session_id = session_payload["id"]
    assert session_payload["title"] == "准考证咨询"

    list_response = client.get(
        f"{settings.API_V1_STR}/gwy/chat/sessions",
        headers=normal_user_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] >= 1

    empty_messages = client.get(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/messages",
        headers=normal_user_token_headers,
    )
    assert empty_messages.status_code == 200
    assert empty_messages.json()["count"] == 0

    send_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/messages",
        headers=normal_user_token_headers,
        json={
            "query": "如何打印准考证？",
            "year": 2026,
            "exam_type": "national",
            "doc_group": "exam_affairs_qa",
            "top_k": 5,
            "use_rerank": True,
        },
    )
    assert send_response.status_code == 200
    send_payload = send_response.json()
    assert send_payload["assistant_message"]["role"] == "assistant"
    assert send_payload["session"]["last_intent"] == "admission_ticket"
    assert send_payload["citations"][0]["doc_title"] == "如何打印准考证"

    messages_response = client.get(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/messages",
        headers=normal_user_token_headers,
    )
    assert messages_response.status_code == 200
    messages = messages_response.json()["data"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_chat_stream_falls_back_when_llm_stream_returns_empty(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyStreamPolicyRagService:
        def __init__(self, session: Session | None = None, **_: object) -> None:
            self.session_service = ChatSessionService(session)  # type: ignore[arg-type]
            self.chat_service = self

        def stream_chat_completion(
            self,
            messages: list[dict[str, object]],  # noqa: ARG002
            temperature: float = 0.2,  # noqa: ARG002
        ):
            if False:
                yield ""
            return

        def _node_route_intent(self, state: dict[str, object]) -> dict[str, object]:
            return {"intent": "general_chat", "need_rag": False}

        def _load_session_attachments(self, **_: object) -> list[object]:
            return []

        def _build_direct_answer_prompt(self, state: dict[str, object]) -> str:  # noqa: ARG002
            return "prompt"

        def _generate_direct_answer(self, prompt: str, state: dict[str, object]) -> str:  # noqa: ARG002
            return "兜底回答"

        def _normalize_answer_text(self, text: str) -> str:
            return text.strip()

        def _build_result_payload(
            self,
            state: dict[str, object],
            answer: str,
        ) -> dict[str, object]:
            return {
                "answer": answer,
                "intent": state.get("intent"),
                "need_rag": state.get("need_rag", False),
                "citations": [],
                "retrieval_trace": [],
                "recommendations": [],
                "need_more_info": False,
                "missing_fields": [],
                "historical_reference": False,
            }

        def finalize_chat_turn(
            self,
            *,
            session_id: UUID,
            user_id: UUID,
            query: str,
            user_message: dict[str, object],  # noqa: ARG002
            result: dict[str, object],
        ) -> dict[str, object]:
            assistant_message = self.session_service.append_message(
                session_id=session_id,
                role="assistant",
                content=str(result["answer"]),
                intent=str(result["intent"]),
                historical_reference=bool(result["historical_reference"]),
                citations=list(result["citations"]),
                retrieval_trace=list(result["retrieval_trace"]),
                metadata_json={},
            )
            session = self.session_service.update_session_state(
                session_id=session_id,
                user_id=user_id,
                summary=f"用户：{query}；助手：{result['answer']}",
                last_intent=str(result["intent"]),
                active_topic="general_chat",
                mentioned_docs=[],
            )
            return {
                **result,
                "session": {
                    "id": str(session.id),
                    "title": session.title,
                    "last_intent": session.last_intent,
                    "active_topic": session.active_topic,
                    "mentioned_docs": list(session.mentioned_docs or []),
                    "summary": session.summary,
                    "created_at": session.created_at,
                },
                "assistant_message": {
                    "id": str(assistant_message.id),
                    "session_id": str(assistant_message.session_id),
                    "role": assistant_message.role,
                    "content": assistant_message.content,
                },
            }

    monkeypatch.setattr(gwy_routes, "PolicyRagService", EmptyStreamPolicyRagService)

    create_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions",
        headers=normal_user_token_headers,
        json={"title": "流式兜底测试"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/messages/stream",
        headers=normal_user_token_headers,
        json={
            "query": "我叫什么名字",
            "year": 2026,
            "exam_type": "national",
            "doc_group": None,
            "top_k": 5,
            "use_rerank": True,
            "mode": "general_chat",
        },
    )

    assert response.status_code == 200
    assert "兜底回答" in response.text


def test_chat_session_delete_api_removes_session(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    tmp_path,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions",
        headers=normal_user_token_headers,
        json={"title": "删除测试会话"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["id"]
    session_uuid = UUID(session_id)

    session_service = ChatSessionService(db)
    session_service.append_message(
        session_id=session_uuid,
        role="user",
        content="测试消息",
    )

    upload_file = tmp_path / "sample.txt"
    upload_file.write_text("attachment", encoding="utf-8")
    session_service.add_attachment(
        session_id=session_uuid,
        file_name="sample.txt",
        original_name="sample.txt",
        attachment_type="other",
        mime_type="text/plain",
        file_path=str(upload_file),
        size_bytes=upload_file.stat().st_size,
    )

    created_session = db.get(GwyChatSession, session_uuid)
    assert created_session is not None
    db.add(
        GwyConversationMemory(
            user_id=created_session.user_id,
            conversation_id=session_id,
            memory_key="summary",
            memory_value={"summary": "cached"},
        )
    )
    db.add(
        GwyRagCacheEntry(
            session_id=session_uuid,
            query_hash="delete-test-cache",
            request_json={"query": "测试"},
            response_json={"answer": "cached"},
        )
    )
    db.commit()

    delete_response = client.delete(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}",
        headers=normal_user_token_headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Chat session deleted"

    assert db.get(GwyChatSession, session_uuid) is None
    assert (
        db.exec(
            select(GwyChatMessage).where(GwyChatMessage.session_id == session_uuid)
        ).all()
        == []
    )
    assert (
        db.exec(
            select(GwyChatAttachment).where(
                GwyChatAttachment.session_id == session_uuid
            )
        ).all()
        == []
    )
    assert (
        db.exec(
            select(GwyConversationMemory).where(
                GwyConversationMemory.conversation_id == session_id
            )
        ).all()
        == []
    )
    assert (
        db.exec(
            select(GwyRagCacheEntry).where(
                GwyRagCacheEntry.session_id == session_uuid
            )
        ).all()
        == []
    )
    assert upload_file.exists() is False


def test_chat_session_attachments_are_consumed_after_one_turn(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    tmp_path,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions",
        headers=normal_user_token_headers,
        json={"title": "附件消费测试"},
    )
    assert create_response.status_code == 200
    session_id = UUID(create_response.json()["id"])

    upload_file = tmp_path / "sample.png"
    upload_file.write_bytes(b"image-bytes")

    created_session = db.get(GwyChatSession, session_id)
    assert created_session is not None

    service = ChatSessionService(db)
    service.add_attachment(
        session_id=session_id,
        file_name="sample.png",
        original_name="sample.png",
        attachment_type="image",
        mime_type="image/png",
        file_path=str(upload_file),
        size_bytes=upload_file.stat().st_size,
    )

    active_before = service.list_active_attachments(
        session_id,
        created_session.user_id,
    )
    assert len(active_before) == 1

    service.consume_attachments(session_id, created_session.user_id)

    active_after = service.list_active_attachments(
        session_id,
        created_session.user_id,
    )
    assert active_after == []

    attachments = service.list_attachments(session_id, created_session.user_id)
    assert len(attachments) == 1
    assert bool(attachments[0].metadata_json.get("context_consumed")) is True

def test_chat_attachment_upload_returns_404_for_missing_session(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions/00000000-0000-0000-0000-000000000001/attachments",
        headers=normal_user_token_headers,
        files=[("files", ("sample.txt", b"hello", "text/plain"))],
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Chat session not found."


def test_chat_attachment_upload_falls_back_to_multimodal_summary_for_pdf_without_text(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions",
        headers=normal_user_token_headers,
        json={"title": "PDF 兜底测试"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["id"]

    pdf_path = tmp_path / "scanned.pdf"
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "")
    document.save(str(pdf_path))
    document.close()

    class FakeMultimodalSummaryService:
        def summarize_image(self, **kwargs: object) -> dict[str, object]:
            _ = kwargs
            return {
                "summary": "第1页：报名条件、流程与注意事项",
                "ocr_text": "报名条件、流程与注意事项",
                "extraction_status": "success",
            }

    monkeypatch.setattr(gwy_routes, "MultimodalSummaryService", FakeMultimodalSummaryService)

    upload_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/attachments",
        headers=normal_user_token_headers,
        files=[("files", ("scanned.pdf", pdf_path.read_bytes(), "application/pdf"))],
    )

    assert upload_response.status_code == 200
    payload = upload_response.json()
    assert payload["count"] == 1
    attachment = payload["data"][0]
    assert attachment["attachment_type"] == "pdf"
    assert attachment["extraction_status"] == "multimodal_summary"
    assert "报名条件" in attachment["summary"]
    assert "报名条件" in attachment["extracted_text"]


def test_chat_attachment_delete_api_removes_attachment(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions",
        headers=normal_user_token_headers,
        json={"title": "删除附件测试"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["id"]
    session_uuid = UUID(session_id)

    upload_response = client.post(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/attachments",
        headers=normal_user_token_headers,
        files=[("files", ("sample.txt", b"hello", "text/plain"))],
    )
    assert upload_response.status_code == 200
    attachment_payload = upload_response.json()["data"][0]
    attachment_id = attachment_payload["id"]
    file_path = Path(attachment_payload["file_path"])

    delete_response = client.delete(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/attachments/{attachment_id}",
        headers=normal_user_token_headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Chat attachment deleted"

    list_response = client.get(
        f"{settings.API_V1_STR}/gwy/chat/sessions/{session_id}/attachments",
        headers=normal_user_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 0

    assert db.get(GwyChatAttachment, UUID(attachment_id)) is None
    assert file_path.exists() is False
    assert db.get(GwyChatSession, session_uuid) is not None


def test_batch_stream_chunks_coalesces_tiny_streams() -> None:
    chunks = ["你", "好", "，", "今", "天", "要", "测", "试", "。", "另", "一", "句"]

    batched = list(
        gwy_routes._batch_stream_chunks(
            iter(chunks),
            min_chars=4,
            max_chars=12,
        )
    )

    assert batched == ["你好，今天要测试。", "另一句"]
