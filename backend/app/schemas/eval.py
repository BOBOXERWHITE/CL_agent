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
    # P0: per-sample LLM-as-judge breakdown. Defaults preserve backward
    # compatibility for legacy eval_run rows persisted before the judge
    # was added (judge_* fields will simply be missing from metrics_json).
    judge_answer_correct: bool = False
    judge_faithfulness: float = 0.0
    judge_reasoning: str = ""
    judge_fallback_used: bool = True
    # P1: RAGAS-aligned per-sample context metrics. Defaults to 0 so
    # legacy rows persisted before P1 still validate cleanly.
    context_precision: float = 0.0
    context_recall: float = 0.0


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
    # P0: LLM-as-judge metrics, RAGAS-aligned naming. Default 0.0 so old
    # rows persisted before the judge shipped still validate cleanly.
    # ``judge_fallback_rate`` = fraction of samples graded by keyword
    # fallback (judge disabled or LLM call failed) — useful to disclose
    # how much of the headline number came from the LLM vs. a string match.
    judge_answer_correctness: float = 0.0
    faithfulness: float = 0.0
    judge_fallback_rate: float = 1.0
    # P1: RAGAS-aligned dataset-level context metrics.
    # context_precision: how concentrated are relevant chunks at the
    # top of retrieval (1.0 = all relevant chunks ranked first).
    # context_recall: fraction of expected keyword atoms reached by
    # the union of retrieved chunks (1.0 = every gold fact made it
    # into the LLM's context window).
    context_precision: float = 0.0
    context_recall: float = 0.0


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
