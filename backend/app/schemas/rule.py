from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.agent import AgentCheckpointPayload


class PolicyRulePayload(BaseModel):
    id: str
    rule_code: str
    expense_type: str
    city_tier: str
    threshold_amount: float
    decision_on_exceed: str
    description: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PolicyRuleListResponse(BaseModel):
    items: list[PolicyRulePayload]


class RuleEvaluationRequest(BaseModel):
    amount: float = Field(ge=0)
    city_tier: str = Field(min_length=1)
    expense_type: str = Field(min_length=1)


class RuleHitPayload(BaseModel):
    rule_code: str
    decision: str
    threshold_amount: float
    actual_amount: float
    reason: str


class RuleEvaluationResponse(BaseModel):
    decision: str
    reason: str
    suggested_action: str
    rule_hits: list[RuleHitPayload]


class ReviewIngestRequest(BaseModel):
    source: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    tenant_id: str = "default-tenant"
    customer_id: str = "default-customer"
    reason: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    rule_result: dict[str, Any] = Field(default_factory=dict)


class ReviewCasePayload(BaseModel):
    id: str
    source: str
    tenant_id: str
    customer_id: str
    agent_run_id: str | None = None
    thread_id: str | None = None
    status: str
    confidence: float
    reason: str
    suggested_action: str
    payload: dict[str, Any]
    rule_result: dict[str, Any]
    pending_interrupt: dict[str, Any] = Field(default_factory=dict)
    latest_checkpoint: AgentCheckpointPayload | None = None
    trace_events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReviewCaseListResponse(BaseModel):
    items: list[ReviewCasePayload]
