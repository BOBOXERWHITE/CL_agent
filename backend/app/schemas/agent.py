from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TicketPayload(BaseModel):
    ticket_id: str = Field(min_length=1)
    expense_type: str = Field(min_length=1)
    city: str = Field(min_length=1)
    amount: float = Field(ge=0)
    status: str = Field(min_length=1)


class AgentRunCreateRequest(BaseModel):
    question: str = Field(min_length=1)
    tenant_id: str = "default-tenant"
    customer_id: str = "default-customer"
    ticket: TicketPayload | None = None


class TimelineStepPayload(BaseModel):
    node_name: str
    status: str
    detail: str
    timestamp: datetime


class ToolCallPayload(BaseModel):
    tool_name: str
    status: str
    latency_ms: int
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]


class AgentRunPayload(BaseModel):
    id: str
    agent_name: str
    route_name: str
    status: str
    confidence: float
    requires_human_review: bool
    output: dict[str, Any]
    timeline: list[TimelineStepPayload]
    tool_calls: list[ToolCallPayload]
    created_at: datetime
    updated_at: datetime


class AgentRunListResponse(BaseModel):
    items: list[AgentRunPayload]


class AgentRunResumeRequest(BaseModel):
    """Reviewer-provided decision on a paused agent run (P3.8 HITL).

    ``decision`` is the terminal outcome the reviewer chose; ``note`` is an
    optional free-form reasoning that lands in the audit log and the
    ReviewCase resolution.
    """

    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=2000)
