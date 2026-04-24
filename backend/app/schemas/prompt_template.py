from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PromptTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    task_type: str = Field(min_length=1, max_length=64)
    template: str = Field(min_length=1)


class PromptTemplatePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    task_type: str
    template: str
    version: int
    status: str
    # P6.1: rollout percentage for ``candidate`` status. Always present
    # in the payload (default 0) so the frontend can display it without
    # defensive null handling.
    traffic_percent: int = 0
    created_at: datetime
    updated_at: datetime


class PromptTemplateListResponse(BaseModel):
    items: list[PromptTemplatePayload]


class PromptTemplateTransitionRequest(BaseModel):
    """P6.1: explicit state transitions.

    ``target_status`` is the requested end state; ``traffic_percent`` is
    only honored for ``candidate``. Used by the new endpoints added in
    P6.4 (promote / rollback / set-candidate-traffic).
    """

    target_status: str = Field(pattern="^(draft|candidate|active|archived)$")
    traffic_percent: int = Field(default=0, ge=0, le=100)
