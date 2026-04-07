from __future__ import annotations

from pydantic import BaseModel, Field


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1)
    tenant_id: str = "default-tenant"
    customer_id: str = "default-customer"
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


class RetrievalTraceChunkPayload(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    score: float


class RetrievalTracePayload(BaseModel):
    mode: str
    prompt_name: str
    prompt_version: int
    model_name: str
    token_usage: TokenUsagePayload
    selected_chunks: list[RetrievalTraceChunkPayload]


class ChatAskResponse(BaseModel):
    session_id: str
    answer: str
    confidence: float
    citations: list[CitationPayload]
    retrieval_trace: RetrievalTracePayload | None = None
