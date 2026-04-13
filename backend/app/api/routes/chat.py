from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.core.security import AuthContext, require_roles
from app.db.models.conversation import ChatMessage, ChatSession
from app.db.models.rag_recall_log import RagRecallLog
from app.db.session import get_session, init_db
from app.schemas.chat import ChatAskRequest, ChatAskResponse, CitationPayload, RetrievalTracePayload
from app.services.rag.query_engine import answer_policy_question
from app.services.system_settings import get_effective_business_settings


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/ask", response_model=ChatAskResponse)
def ask_policy_question(
    payload: ChatAskRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> ChatAskResponse:
    init_db()
    business_settings = get_effective_business_settings()
    request.state.request_id = context.request_id
    tenant_id = payload.tenant_id or business_settings.default_tenant_id
    customer_id = payload.customer_id or business_settings.default_customer_id
    request.state.tenant_id = tenant_id
    request.state.customer_id = customer_id
    result = answer_policy_question(
        question=payload.question,
        tenant_id=tenant_id,
        customer_id=customer_id,
    )
    request.state.model_name = result.retrieval_trace.model_name
    request.state.token_usage = result.retrieval_trace.token_usage

    session_id = payload.session_id or str(uuid4())
    request.state.session_id = session_id
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        chat_session = ChatSession(
            id=session_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
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
                "retrieval_trace": result.retrieval_trace.as_dict(),
            },
        )
    )
    session.add(
        RagRecallLog(
            id=str(uuid4()),
            request_id=context.request_id,
            session_id=session_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            question=payload.question,
            retrieval_mode=result.retrieval_trace.mode,
            prompt_template_id=result.prompt_template_id,
            prompt_name=result.retrieval_trace.prompt_name,
            prompt_version=result.retrieval_trace.prompt_version,
            model_name=result.retrieval_trace.model_name,
            citation_count=len(result.citations),
            token_usage_json=result.retrieval_trace.token_usage,
            trace_json=result.retrieval_trace.as_dict(),
        )
    )
    session.commit()

    return ChatAskResponse(
        session_id=session_id,
        answer=result.answer,
        confidence=result.confidence,
        citations=[CitationPayload.model_validate(citation.__dict__) for citation in result.citations],
        retrieval_trace=RetrievalTracePayload.model_validate(result.retrieval_trace.as_dict()),
    )
