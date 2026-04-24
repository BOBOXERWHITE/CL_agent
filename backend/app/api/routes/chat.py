from __future__ import annotations

import json
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.api.guards import require_tenant_match
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import AuthContext, require_roles
from app.db.models.conversation import ChatMessage, ChatSession
from app.db.models.rag_recall_log import RagRecallLog
from app.db.session import get_session
from app.schemas.chat import (
    ChatAskRequest,
    ChatAskResponse,
    CitationPayload,
    LlmReadinessPayload,
    LlmSmokeTestPayload,
    RetrievalTracePayload,
)
from app.services.llm.client import check_llm_readiness, run_llm_smoke_test
from app.services.rag.query_engine import (
    PolicyAnswerResult,
    StreamReadyContext,
    answer_policy_question_async,
    build_policy_answer_from_stream,
    prepare_answer_context_async,
    stream_answer_from_context,
)
from app.services.system_settings import get_effective_business_settings

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/llm-readiness", response_model=LlmReadinessPayload)
def get_llm_readiness(
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> LlmReadinessPayload:
    readiness = check_llm_readiness()
    return LlmReadinessPayload(
        provider=readiness.provider,
        model_name=readiness.model_name,
        configured=readiness.configured,
        available=readiness.available,
        status=readiness.status,
        message=readiness.message,
        endpoint=readiness.endpoint,
    )


@router.post("/llm-smoke-test", response_model=LlmSmokeTestPayload)
def post_llm_smoke_test(
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> LlmSmokeTestPayload:
    result = run_llm_smoke_test()
    return LlmSmokeTestPayload(
        provider=result.provider,
        model_name=result.model_name,
        configured=result.configured,
        available=result.available,
        status=result.status,
        message=result.message,
        sample_question=result.sample_question,
        sample_evidence=result.sample_evidence,
        answer_preview=result.answer_preview,
        latency_ms=result.latency_ms,
        token_usage=result.token_usage,
        endpoint=result.endpoint,
    )


@router.post("/ask", response_model=ChatAskResponse)
@limiter.limit(lambda: get_settings().rate_limit_chat_ask)
async def ask_policy_question(
    payload: ChatAskRequest,
    request: Request,
    response: Response,  # required by slowapi for X-RateLimit-* header injection
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> ChatAskResponse:
    """Chat entry point — now ``async def`` (P4.2).

    The sync DB session is still injected; short queries don't need
    async wrapping and the rest of the stack (audit / recall log) is
    microseconds. The heavy lifting (LLM rewrite + answer generation)
    is awaited via :func:`answer_policy_question_async`, so uvicorn
    workers can interleave requests instead of serialising them.
    """
    business_settings = get_effective_business_settings()
    request.state.request_id = context.request_id
    # P1.3: prevent body-supplied tenant_id from escaping the JWT claim.
    # Pass payload.tenant_id directly so the guard can fall back to ctx
    # when the body omits it; only substitute the business default when
    # both ctx and body provide nothing useful (static-token mode).
    tenant_id = require_tenant_match(payload.tenant_id, context)
    if not tenant_id:
        tenant_id = business_settings.default_tenant_id
    customer_id = payload.customer_id or business_settings.default_customer_id
    request.state.tenant_id = tenant_id
    request.state.customer_id = customer_id
    started_at = perf_counter()
    result = await answer_policy_question_async(
        question=payload.question,
        tenant_id=tenant_id,
        customer_id=customer_id,
    )
    latency_ms = int((perf_counter() - started_at) * 1000)
    request.state.model_name = result.retrieval_trace.model_name
    request.state.token_usage = result.retrieval_trace.token_usage
    # P5.2: let the token aggregate sink attribute to the chat flow.
    request.state.agent_name = "chat"

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
            # P7.3: expose latency + confidence as first-class columns
            # so stats / SLO queries don't need JSON path extraction.
            latency_ms=latency_ms,
            confidence=result.confidence,
        )
    )
    record_audit(
        session,
        request=request,
        ctx=context,
        action="chat.ask",
        target_type="ChatSession",
        target_id=session_id,
        payload={
            "question_chars": len(payload.question),
            "confidence": result.confidence,
            "citation_count": len(result.citations),
            "session_reused": payload.session_id is not None,
        },
    )
    session.commit()

    return ChatAskResponse(
        session_id=session_id,
        answer=result.answer,
        confidence=result.confidence,
        citations=[
            CitationPayload.model_validate(citation.__dict__) for citation in result.citations
        ],
        retrieval_trace=RetrievalTracePayload.model_validate(result.retrieval_trace.as_dict()),
    )


# ---------------------------------------------------------------------------
# P6.5: SSE streaming
# ---------------------------------------------------------------------------


def _sse_event(payload: dict) -> bytes:
    """Format one payload as a Server-Sent Event frame.

    ``data: {...}\n\n`` is the minimum viable SSE envelope; we skip
    ``event:`` / ``id:`` fields because the client side can infer type
    from the JSON ``event`` field.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@router.post("/ask/stream")
@limiter.limit(lambda: get_settings().rate_limit_chat_ask)
async def stream_policy_question(
    payload: ChatAskRequest,
    request: Request,
    response: Response,  # slowapi header injection
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """P6.5: streaming chat answer.

    Uses the existing ``answer_policy_question_async`` for rewrite /
    retrieve / evidence scoring, then replaces the final generation
    step with a ``stream_answer_async`` call that yields tokens as they
    arrive. Events emitted to the client:

    - ``{"event": "start", "session_id": ...}`` — once at the beginning
    - ``{"event": "delta", "text": "..."}`` — per-token
    - ``{"event": "citations", "citations": [...], "confidence": ...}``
      — after the retrieval step, before the first delta
    - ``{"event": "done", "token_usage": {...}, "model": "..."}``
      — on stream close
    - ``{"event": "error", "message": "..."}`` — any failure

    Persistence (ChatMessage / RagRecallLog / audit) happens after the
    stream completes, same as the non-streaming endpoint, so the
    resulting data is identical regardless of transport choice.
    """
    business_settings = get_effective_business_settings()
    request.state.request_id = context.request_id
    tenant_id = require_tenant_match(payload.tenant_id, context)
    if not tenant_id:
        tenant_id = business_settings.default_tenant_id
    customer_id = payload.customer_id or business_settings.default_customer_id
    request.state.tenant_id = tenant_id
    request.state.customer_id = customer_id

    # Run the full QA pipeline but then swap the final answer text for
    # a streamed one. Simplest wire: run ``answer_policy_question_async``
    # for the non-stream path, then stream the *pre-computed* answer
    # token-group by token-group. That keeps the cache / citations /
    # confidence logic untouched. The user still sees a "typed"
    # experience because we artificially chunk the text.
    #
    # A future iteration can push the real OpenAI ``stream=true`` call
    # down through the engine; the ``stream_answer_async`` infra is
    # already in place for that. Phase 6 keeps the deterministic path.
    stream_started_at = perf_counter()
    # P7.1: prepare phase only — no LLM call yet. Returns either an
    # early-exit PolicyAnswerResult (no-evidence / low-confidence /
    # cache-hit) or a StreamReadyContext the generation loop consumes.
    prepared = await prepare_answer_context_async(
        question=payload.question,
        tenant_id=tenant_id,
        customer_id=customer_id,
    )

    session_id = payload.session_id or str(uuid4())
    request.state.session_id = session_id
    request.state.agent_name = "chat"

    async def _event_generator():
        nonlocal prepared
        # Head-of-stream metadata.
        yield _sse_event({"event": "start", "session_id": session_id})

        if isinstance(prepared, PolicyAnswerResult):
            # Early-exit path: no LLM streaming, answer is already
            # complete. One delta + done + persistence, same as before.
            result: PolicyAnswerResult = prepared
            yield _sse_event(
                {
                    "event": "citations",
                    "confidence": result.confidence,
                    "citations": [c.__dict__ for c in result.citations],
                    "retrieval_mode": result.retrieval_trace.mode,
                }
            )
            yield _sse_event({"event": "delta", "text": result.answer})
            await _persist_chat(
                result=result,
                session=session,
                request=request,
                payload=payload,
                context=context,
                tenant_id=tenant_id,
                customer_id=customer_id,
                session_id=session_id,
                latency_ms=int((perf_counter() - stream_started_at) * 1000),
            )
            yield _sse_event(
                {
                    "event": "done",
                    "token_usage": result.retrieval_trace.token_usage,
                    "model": result.retrieval_trace.model_name,
                    "session_id": session_id,
                }
            )
            return

        # Streaming path: emit citations up front, then push LLM
        # tokens as they arrive.
        ctx: StreamReadyContext = prepared
        yield _sse_event(
            {
                "event": "citations",
                "confidence": round(ctx.top_score, 4),
                "citations": [c.__dict__ for c in ctx.citations],
                "retrieval_mode": ctx.retrieval_mode,
            }
        )

        generation_started_at = perf_counter()
        collected: list[str] = []
        final_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        final_model = ctx.client_model_name
        try:
            async for chunk in stream_answer_from_context(ctx):
                if chunk.done:
                    if chunk.token_usage:
                        final_usage = dict(chunk.token_usage)
                    if chunk.model_name:
                        final_model = chunk.model_name
                    break
                collected.append(chunk.delta)
                if chunk.model_name:
                    final_model = chunk.model_name
                yield _sse_event({"event": "delta", "text": chunk.delta})
        except Exception as exc:
            yield _sse_event({"event": "error", "message": str(exc)})
            return

        generation_elapsed_ms = int((perf_counter() - generation_started_at) * 1000)
        result = build_policy_answer_from_stream(
            ctx,
            collected_text="".join(collected),
            token_usage=final_usage,
            model_name=final_model,
            generation_elapsed_ms=generation_elapsed_ms,
        )
        try:
            await _persist_chat(
                result=result,
                session=session,
                request=request,
                payload=payload,
                context=context,
                tenant_id=tenant_id,
                customer_id=customer_id,
                session_id=session_id,
                latency_ms=int((perf_counter() - stream_started_at) * 1000),
            )
        except Exception as exc:
            yield _sse_event({"event": "error", "message": str(exc)})
            return

        yield _sse_event(
            {
                "event": "done",
                "token_usage": result.retrieval_trace.token_usage,
                "model": result.retrieval_trace.model_name,
                "session_id": session_id,
            }
        )

    # Disable proxy buffering — critical for small deployments behind
    # nginx / cloudflare; without this the client sees the response
    # all at once instead of incrementally.
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _persist_chat(
    *,
    result: PolicyAnswerResult,
    session: Session,
    request: Request,
    payload: ChatAskRequest,
    context: RequestContext,
    tenant_id: str,
    customer_id: str,
    session_id: str,
    latency_ms: int,
) -> None:
    """P7.1: write ChatSession / ChatMessage / RagRecallLog / audit
    rows for a streaming chat turn.

    Extracted so both the streaming early-exit and the streaming
    generation paths share the exact same persistence shape as the
    non-streaming ``/ask`` endpoint. Exceptions bubble — the caller
    turns them into an ``error`` SSE event.
    """
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        session.add(
            ChatSession(
                id=session_id,
                tenant_id=tenant_id,
                customer_id=customer_id,
            )
        )
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
                "citations": [c.__dict__ for c in result.citations],
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
            latency_ms=latency_ms,
            confidence=result.confidence,
        )
    )
    record_audit(
        session,
        request=request,
        ctx=context,
        action="chat.ask.stream",
        target_type="ChatSession",
        target_id=session_id,
        payload={
            "question_chars": len(payload.question),
            "confidence": result.confidence,
            "citation_count": len(result.citations),
            "session_reused": payload.session_id is not None,
        },
    )
    request.state.session_id = session_id
    request.state.model_name = result.retrieval_trace.model_name
    request.state.token_usage = result.retrieval_trace.token_usage
    session.commit()
