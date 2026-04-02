from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter

from app.db.models.conversation import ChatMessage, ChatSession
from app.db.session import SessionLocal, init_db
from app.schemas.chat import ChatAskRequest, ChatAskResponse, CitationPayload
from app.services.rag.query_engine import answer_policy_question


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/ask", response_model=ChatAskResponse)
def ask_policy_question(payload: ChatAskRequest) -> ChatAskResponse:
    init_db()
    result = answer_policy_question(
        question=payload.question,
        tenant_id=payload.tenant_id,
        customer_id=payload.customer_id,
    )

    with SessionLocal() as session:
        session_id = payload.session_id or str(uuid4())
        chat_session = session.get(ChatSession, session_id)
        if chat_session is None:
            chat_session = ChatSession(
                id=session_id,
                tenant_id=payload.tenant_id,
                customer_id=payload.customer_id,
            )
            session.add(chat_session)

        session.add(
            ChatMessage(
                id=str(uuid4()),
                session_id=session_id,
                role="user",
                content=payload.question,
                metadata_json={},
            )
        )
        session.add(
            ChatMessage(
                id=str(uuid4()),
                session_id=session_id,
                role="assistant",
                content=result.answer,
                metadata_json={
                    "confidence": result.confidence,
                    "citations": [citation.__dict__ for citation in result.citations],
                },
            )
        )
        session.commit()

    return ChatAskResponse(
        session_id=session_id,
        answer=result.answer,
        confidence=result.confidence,
        citations=[CitationPayload.model_validate(citation.__dict__) for citation in result.citations],
    )
