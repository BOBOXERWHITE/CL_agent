from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RuntimeLogPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    method: str
    path: str
    status_code: int
    latency_ms: int
    tenant_id: str | None = None
    customer_id: str | None = None
    session_id: str | None = None
    user_role: str | None = None
    model_name: str | None = None
    token_usage_json: dict[str, int] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime


class RuntimeLogListResponse(BaseModel):
    items: list[RuntimeLogPayload]
