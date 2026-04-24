"""Integration test: end-to-end chat / RAG against real Postgres + real MinIO.

Note: vector store remains ``noop`` in Phase 0 — retrieval is driven by the
lexical path over Postgres. Milvus integration tests are scheduled for P2.8
when the vector store itself is refactored.

Verifies:
- POST /api/chat/ask round-trips through a real PG backend.
- ChatSession / ChatMessage / RagRecallLog rows persist correctly.
- Session re-use works across two calls (second call hits the same session_id).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import DOCX_CONTENT_TYPE

pytestmark = pytest.mark.integration


def test_chat_ask_persists_session_messages_and_recall_log(
    integration_client,
    multilingual_docx_file: bytes,
) -> None:
    upload_response = integration_client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("rag-policy.docx", multilingual_docx_file, DOCX_CONTENT_TYPE)},
    )
    assert upload_response.status_code == 202

    ask_response = integration_client.post(
        "/api/chat/ask",
        json={
            "question": "北京酒店报销上限是多少？",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )
    assert ask_response.status_code == 200
    payload = ask_response.json()
    session_id = payload["session_id"]
    assert session_id
    assert payload["answer"]

    from app.db.models.conversation import ChatMessage, ChatSession
    from app.db.models.rag_recall_log import RagRecallLog
    from app.db.session import SessionLocal

    session: Session = SessionLocal()
    try:
        chat_session = session.get(ChatSession, session_id)
        assert chat_session is not None
        assert chat_session.tenant_id == "t1"

        messages = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        ).all()
        # One user message + one assistant message.
        assert len(messages) == 2
        assert {m.role for m in messages} == {"user", "assistant"}

        recall_logs = session.scalars(
            select(RagRecallLog).where(RagRecallLog.session_id == session_id)
        ).all()
        assert len(recall_logs) >= 1
    finally:
        session.close()


def test_chat_ask_reuses_session_when_session_id_provided(
    integration_client,
    multilingual_docx_file: bytes,
) -> None:
    integration_client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("x.docx", multilingual_docx_file, DOCX_CONTENT_TYPE)},
    )

    first = integration_client.post(
        "/api/chat/ask",
        json={
            "question": "北京酒店报销上限是多少？",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    second = integration_client.post(
        "/api/chat/ask",
        json={
            "question": "Shanghai hotel reimbursement cap?",
            "tenant_id": "t1",
            "customer_id": "c1",
            "session_id": session_id,
        },
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id

    from app.db.models.conversation import ChatMessage
    from app.db.session import SessionLocal

    session: Session = SessionLocal()
    try:
        messages = session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id)
        ).all()
        # Two questions + two answers in the same session.
        assert len(messages) == 4
    finally:
        session.close()
