from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.core.errors import NotFound
from app.core.security import AuthContext, require_roles
from app.db.models.conversation import ChatMessage, ChatSession
from app.db.models.prompt_feedback import ALLOWED_RATINGS, PromptFeedback
from app.db.session import get_session
from app.schemas.prompt_feedback import (
    PromptFeedbackRequest,
    PromptFeedbackResponse,
    PromptTemplateStatsResponse,
)
from app.schemas.prompt_template import (
    PromptTemplateCreateRequest,
    PromptTemplateListResponse,
    PromptTemplatePayload,
    PromptTemplateTransitionRequest,
)
from app.services.prompts.service import (
    PromptStateError,
    activate_prompt_template,
    create_prompt_template,
    list_prompt_templates,
    transition_prompt_template,
)
from app.services.prompts.stats import compute_prompt_stats

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("", response_model=PromptTemplateListResponse)
def list_prompts(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> PromptTemplateListResponse:
    items = list_prompt_templates(session)
    return PromptTemplateListResponse(
        items=[PromptTemplatePayload.model_validate(item) for item in items]
    )


@router.post("", response_model=PromptTemplatePayload, status_code=status.HTTP_201_CREATED)
def create_prompt(
    payload: PromptTemplateCreateRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> PromptTemplatePayload:
    request.state.request_id = context.request_id
    prompt_template = create_prompt_template(
        session,
        name=payload.name,
        task_type=payload.task_type,
        template=payload.template,
    )
    return PromptTemplatePayload.model_validate(prompt_template)


@router.post("/{prompt_template_id}/activate", response_model=PromptTemplatePayload)
def activate_prompt(
    prompt_template_id: str,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> PromptTemplatePayload:
    request.state.request_id = context.request_id
    try:
        prompt_template = activate_prompt_template(session, prompt_template_id)
    except LookupError as error:
        raise NotFound(
            "prompt template not found",
            error_code="PROMPT_TEMPLATE_NOT_FOUND",
        ) from error

    return PromptTemplatePayload.model_validate(prompt_template)


@router.post(
    "/{prompt_template_id}/promote",
    response_model=PromptTemplatePayload,
)
def promote_prompt(
    prompt_template_id: str,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> PromptTemplatePayload:
    """P6.4: promote a candidate (or draft) to active.

    Thin wrapper over :func:`transition_prompt_template` with
    ``target_status=active`` pre-set — preserves the intent in the URL
    so audit logs read naturally ("admin promoted prompt X").
    """
    request.state.request_id = context.request_id
    try:
        updated = transition_prompt_template(session, prompt_template_id, target_status="active")
    except LookupError as error:
        raise NotFound(
            "prompt template not found",
            error_code="PROMPT_TEMPLATE_NOT_FOUND",
        ) from error
    except PromptStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return PromptTemplatePayload.model_validate(updated)


@router.post(
    "/{prompt_template_id}/rollback",
    response_model=PromptTemplatePayload,
)
def rollback_prompt(
    prompt_template_id: str,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> PromptTemplatePayload:
    """P6.4: rollback an active prompt back to archived.

    Per the state machine this is just ``active → archived``; the
    operator would then pick an older archived version, transition it
    to draft (and then active) to complete the rollback. Keeping the
    URL explicit makes the audit trail searchable on ``action=rollback``.
    """
    request.state.request_id = context.request_id
    try:
        updated = transition_prompt_template(session, prompt_template_id, target_status="archived")
    except LookupError as error:
        raise NotFound(
            "prompt template not found",
            error_code="PROMPT_TEMPLATE_NOT_FOUND",
        ) from error
    except PromptStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return PromptTemplatePayload.model_validate(updated)


@router.post(
    "/{prompt_template_id}/transition",
    response_model=PromptTemplatePayload,
)
def transition_prompt(
    prompt_template_id: str,
    payload: PromptTemplateTransitionRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> PromptTemplatePayload:
    """P6.1 / P6.4: explicit state transition with validation.

    ``target_status`` must be one of draft / candidate / active / archived.
    ``traffic_percent`` only applies when target_status=candidate.
    """
    request.state.request_id = context.request_id
    try:
        updated = transition_prompt_template(
            session,
            prompt_template_id,
            target_status=payload.target_status,
            traffic_percent=payload.traffic_percent,
        )
    except LookupError as error:
        raise NotFound(
            "prompt template not found",
            error_code="PROMPT_TEMPLATE_NOT_FOUND",
        ) from error
    except PromptStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return PromptTemplatePayload.model_validate(updated)


@router.get(
    "/{prompt_template_id}/stats",
    response_model=PromptTemplateStatsResponse,
)
def get_prompt_stats(
    prompt_template_id: str,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> PromptTemplateStatsResponse:
    """P6.3: per-version request / up / down / confidence aggregate.

    Admin + operator can see stats (signals the promotion decision).
    Reviewer role is intentionally excluded — spend + adoption metrics
    are privileged.
    """
    request.state.request_id = context.request_id
    stats = compute_prompt_stats(session, prompt_template_id=prompt_template_id)
    if stats is None:
        raise NotFound(
            "prompt template not found",
            error_code="PROMPT_TEMPLATE_NOT_FOUND",
        )
    return PromptTemplateStatsResponse(
        prompt_template_id=stats.prompt_template_id,
        version=stats.version,
        status=stats.status,
        total_requests=stats.total_requests,
        up_count=stats.up_count,
        down_count=stats.down_count,
        up_rate=stats.up_rate,
        avg_confidence=stats.avg_confidence,
        avg_latency_ms=stats.avg_latency_ms,
    )


# Separate feedback router — mounted on /api/chat so the URL reads
# naturally for frontend callers (``POST /api/chat/sessions/{id}/feedback``).
feedback_router = APIRouter(prefix="/api/chat/sessions", tags=["chat"])


@feedback_router.post(
    "/{session_id}/feedback",
    response_model=PromptFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_session_feedback(
    session_id: str,
    payload: PromptFeedbackRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> PromptFeedbackResponse:
    """P6.3: user feedback on a chat session.

    We look up the most recent assistant message in the session and
    pull ``prompt_template_id`` / ``version`` out of its
    ``metadata_json`` so the feedback is attributed to the specific
    prompt variant that produced the answer. Falls back to None when
    the session has no assistant messages yet (rare — but avoids a 5xx
    on a double-click).
    """
    request.state.request_id = context.request_id
    # Tenant check: the session must belong to the caller's tenant.
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        raise NotFound(
            "chat session not found",
            error_code="CHAT_SESSION_NOT_FOUND",
        )
    if chat_session.tenant_id != context.tenant_id and context.tenant_id not in (
        "",
        "default-tenant",
    ):
        raise HTTPException(status_code=403, detail="cross-tenant feedback not allowed")
    request.state.tenant_id = chat_session.tenant_id

    if payload.rating not in ALLOWED_RATINGS:
        raise HTTPException(status_code=422, detail=f"unknown rating {payload.rating!r}")

    # Find the latest assistant message so we can attribute feedback to
    # the exact prompt variant that produced it.
    latest_assistant = (
        session.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    prompt_template_id: str | None = None
    version = 0
    if latest_assistant is not None:
        meta = latest_assistant.metadata_json or {}
        trace = meta.get("retrieval_trace") or {}
        # Prompt template id was stored on RagRecallLog + ChatMessage
        # by the chat route. Be defensive about shape.
        prompt_template_id = trace.get("prompt_template_id") or meta.get("prompt_template_id")
        version = int(trace.get("prompt_version") or meta.get("prompt_version") or 0)

    feedback = PromptFeedback(
        session_id=session_id,
        tenant_id=chat_session.tenant_id,
        prompt_template_id=prompt_template_id,
        version=version,
        rating=payload.rating,
        comment=payload.comment,
        user_id=context.user_id,
    )
    session.add(feedback)
    session.commit()
    session.refresh(feedback)
    return PromptFeedbackResponse(
        id=feedback.id,
        session_id=session_id,
        prompt_template_id=prompt_template_id,
        version=version,
        rating=payload.rating,
    )
