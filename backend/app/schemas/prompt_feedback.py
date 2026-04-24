"""Schemas for P6.3 feedback endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PromptFeedbackRequest(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    comment: str = Field(default="", max_length=2000)


class PromptFeedbackResponse(BaseModel):
    id: int
    session_id: str
    prompt_template_id: str | None
    version: int
    rating: str


class PromptTemplateStatsResponse(BaseModel):
    prompt_template_id: str
    version: int
    status: str
    total_requests: int
    up_count: int
    down_count: int
    up_rate: float | None
    avg_confidence: float | None
    avg_latency_ms: float | None
