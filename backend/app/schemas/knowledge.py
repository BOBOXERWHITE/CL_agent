from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KnowledgeUploadAccepted(BaseModel):
    job_id: str
    document_id: str
    status: str


class KnowledgeEmbeddingProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    model_name: str
    dimension: int
    profile_key: str


class KnowledgeJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    document_id: str
    filename: str
    status: str
    chunk_count: int
    tenant_id: str
    customer_id: str
    created_at: datetime
    updated_at: datetime
    stored_embedding_profile: KnowledgeEmbeddingProfile | None = None
    current_embedding_profile: KnowledgeEmbeddingProfile
    requires_reindex: bool


class KnowledgeJobList(BaseModel):
    items: list[KnowledgeJob]


class KnowledgeRebuildRequest(BaseModel):
    document_id: str | None = None
    stale_only: bool = False


class KnowledgeRebuildResult(BaseModel):
    scope: str
    document_count: int
    chunk_count: int
    document_ids: list[str]


class KnowledgeDeleteResult(BaseModel):
    document_id: str
    filename: str
    chunk_count: int


class KnowledgeEmbeddingReadiness(BaseModel):
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    endpoint: str | None = None


class KnowledgeEmbeddingSmokeTest(BaseModel):
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    endpoint: str | None = None
    sample_text: str
    latency_ms: float
    vector_dimension: int
