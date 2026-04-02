from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KnowledgeUploadAccepted(BaseModel):
    job_id: str
    document_id: str
    status: str


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


class KnowledgeJobList(BaseModel):
    items: list[KnowledgeJob]
