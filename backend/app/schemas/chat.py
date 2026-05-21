from __future__ import annotations

from pydantic import BaseModel, Field


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1)
    tenant_id: str = "default-tenant"
    customer_id: str = "default-customer"
    thread_id: str | None = None
    session_id: str | None = None


class CitationPayload(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    snippet: str
    score: float


class TokenUsagePayload(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LlmReadinessPayload(BaseModel):
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    endpoint: str | None = None


class LlmSmokeTestPayload(BaseModel):
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    sample_question: str
    sample_evidence: str
    answer_preview: str
    latency_ms: float
    token_usage: TokenUsagePayload
    endpoint: str | None = None


class RetrievalTraceChunkPayload(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    score: float


class CragRoundPayload(BaseModel):
    round_index: int
    sufficiency_score: float
    covered_aspects: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list)
    triggered_re_retrieval: bool = False
    new_chunks_added: int = 0
    reasoning: str = ""


class RetrievalTracePayload(BaseModel):
    mode: str
    prompt_name: str
    prompt_version: int
    model_name: str
    token_usage: TokenUsagePayload
    selected_chunks: list[RetrievalTraceChunkPayload]
    original_query: str | None = None
    expanded_query: str | None = None
    rewrite_rules: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    crag_rounds: list[CragRoundPayload] = Field(default_factory=list)


class ChatAskResponse(BaseModel):
    thread_id: str
    session_id: str
    answer: str
    confidence: float
    citations: list[CitationPayload]
    retrieval_trace: RetrievalTracePayload | None = None
