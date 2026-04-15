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
    answer_pass: bool = False
    expected_citation_rank: int | None = None
    low_confidence: bool
    citations: list[str] = Field(default_factory=list)


class EvalProviderSnapshotPayload(BaseModel):
    llm_provider: str
    llm_model_name: str
    embedding_provider: str
    embedding_model_name: str
    vector_store_provider: str


class EvalMetricsPayload(BaseModel):
    answer_correctness: float = 0.0
    answer_recall: float = 0.0
    citation_hit_rate: float = 0.0
    retrieval_hit_rate: float = 0.0
    retrieval_mrr: float = 0.0
    low_confidence_rate: float = 0.0
    answer_pass_rate: float = 0.0
    quality_gate: str | None = None
    quality_gate_reasons: list[str] = Field(default_factory=list)
    provider_snapshot: EvalProviderSnapshotPayload | None = None


class EvalRunPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_name: str
    status: str
    question_count: int
    metrics: EvalMetricsPayload
    details: list[EvalDetailPayload] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvalRunListResponse(BaseModel):
    items: list[EvalRunPayload]
