"""Pydantic schemas for the P4.5 task API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskRunPayload(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    task_name: str
    status: str
    idempotency_key: str | None
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    retries: int
    trace_id: str
    summary: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class TaskRunListResponse(BaseModel):
    items: list[TaskRunPayload]
    total: int
    # Echo the pagination input so the client can bookkeep without
    # re-computing.
    limit: int
    offset: int


class TaskCancelRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


class TaskCancelResponse(BaseModel):
    task: TaskRunPayload
    # True when we actually transitioned the row this call; False when
    # it was already canceled (the endpoint is idempotent).
    transitioned: bool
