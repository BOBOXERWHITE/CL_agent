"""Schemas for the P5.2 ``/api/usage`` endpoint."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class TokenUsageBucket(BaseModel):
    """One row of aggregate usage. ``group_by`` decides which fields
    are meaningful (empty strings for the rest).
    """

    tenant_id: str
    day: date | None = None
    model_name: str
    agent_name: str
    input_tokens: int
    output_tokens: int
    requests: int
    cost_usd_cents: int | None


class TokenUsageSummary(BaseModel):
    """Aggregate totals alongside the bucket list."""

    total_input_tokens: int
    total_output_tokens: int
    total_requests: int
    total_cost_usd_cents: int | None


class TokenUsageResponse(BaseModel):
    items: list[TokenUsageBucket]
    summary: TokenUsageSummary
