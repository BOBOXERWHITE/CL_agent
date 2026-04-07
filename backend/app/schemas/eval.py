from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvalRunCreateRequest(BaseModel):
    dataset_name: str = Field(min_length=1)


class EvalDetailPayload(BaseModel):
    question: str
    answer: str
    expected_citation: str
    expected_answer_keywords: list[str] = Field(default_factory=list)
    confidence: float
    citation_hit: bool
    answer_correct: bool
    low_confidence: bool
    citations: list[str] = Field(default_factory=list)


class EvalRunPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_name: str
    status: str
    question_count: int
    metrics: dict[str, float]
    details: list[EvalDetailPayload] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvalRunListResponse(BaseModel):
    items: list[EvalRunPayload]
