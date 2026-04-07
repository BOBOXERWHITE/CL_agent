from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.core.security import AuthContext, require_roles
from app.db.session import get_session, init_db
from app.schemas.prompt_template import (
    PromptTemplateCreateRequest,
    PromptTemplateListResponse,
    PromptTemplatePayload,
)
from app.services.prompts.service import activate_prompt_template, create_prompt_template, list_prompt_templates


router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("", response_model=PromptTemplateListResponse)
def list_prompts(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> PromptTemplateListResponse:
    init_db()
    items = list_prompt_templates(session)
    return PromptTemplateListResponse(items=[PromptTemplatePayload.model_validate(item) for item in items])


@router.post("", response_model=PromptTemplatePayload, status_code=status.HTTP_201_CREATED)
def create_prompt(
    payload: PromptTemplateCreateRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> PromptTemplatePayload:
    init_db()
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
    init_db()
    request.state.request_id = context.request_id
    try:
        prompt_template = activate_prompt_template(session, prompt_template_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="prompt template not found") from error

    return PromptTemplatePayload.model_validate(prompt_template)
