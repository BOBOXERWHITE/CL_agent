from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeSummaryPayload(BaseModel):
    document_total: int = 0
    completed_total: int = 0
    failed_total: int = 0
    pending_reindex_total: int = 0


class ChatSummaryPayload(BaseModel):
    session_total: int = 0
    message_total: int = 0


class ReviewSummaryPayload(BaseModel):
    open_total: int = 0


class AgentSummaryPayload(BaseModel):
    last_24h_total: int = 0


class EvalSummaryPayload(BaseModel):
    last_24h_total: int = 0


class RequestSummaryPayload(BaseModel):
    last_hour_total: int = 0
    last_hour_error_total: int = 0
    last_hour_p95_latency_ms: int = 0


class RecentRequestPayload(BaseModel):
    id: str
    request_id: str
    path: str
    status_code: int
    created_at: datetime
    error_message: str | None = None


class RecentEvalPayload(BaseModel):
    id: str
    dataset_name: str
    status: str
    created_at: datetime


class RecentAgentRunPayload(BaseModel):
    id: str
    agent_name: str
    status: str
    created_at: datetime


class RecentActivityPayload(BaseModel):
    recent_failed_requests: list[RecentRequestPayload] = Field(default_factory=list)
    recent_eval_runs: list[RecentEvalPayload] = Field(default_factory=list)
    recent_agent_runs: list[RecentAgentRunPayload] = Field(default_factory=list)


class MonitoringOverviewResponse(BaseModel):
    knowledge_summary: KnowledgeSummaryPayload
    chat_summary: ChatSummaryPayload
    review_summary: ReviewSummaryPayload
    agent_summary: AgentSummaryPayload
    eval_summary: EvalSummaryPayload
    request_summary: RequestSummaryPayload
    recent_activity: RecentActivityPayload
