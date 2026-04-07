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
    created_at: datetime
    updated_at: datetime


class PromptTemplateListResponse(BaseModel):
    items: list[PromptTemplatePayload]
