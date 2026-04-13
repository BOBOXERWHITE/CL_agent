from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.agent import AgentRun
from app.db.models.conversation import ChatMessage, ChatSession
from app.db.models.eval import EvalRun
from app.db.models.knowledge import KnowledgeDocument
from app.db.models.runtime_log import RuntimeLog
from app.db.models.rule import ReviewCase
from app.schemas.monitoring import (
    AgentSummaryPayload,
    ChatSummaryPayload,
    EvalSummaryPayload,
    KnowledgeSummaryPayload,
    MonitoringOverviewResponse,
    RecentActivityPayload,
    RecentAgentRunPayload,
    RecentEvalPayload,
    RecentRequestPayload,
    RequestSummaryPayload,
    ReviewSummaryPayload,
)


def _count(session: Session, statement):
    return int(session.execute(statement).scalar() or 0)


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[index]


def build_monitoring_overview(session: Session) -> MonitoringOverviewResponse:
    now = datetime.now(UTC)
    last_day = now - timedelta(hours=24)
    last_hour = now - timedelta(hours=1)

    documents = list(session.execute(select(KnowledgeDocument)).scalars().all())
    knowledge_summary = KnowledgeSummaryPayload(
        document_total=_count(session, select(func.count()).select_from(KnowledgeDocument)),
        completed_total=_count(
            session,
            select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.status == "completed"),
        ),
        failed_total=_count(
            session,
            select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.status == "failed"),
        ),
        pending_reindex_total=sum(
            1
            for document in documents
            if bool((document.attributes_json or {}).get("requires_reindex"))
        ),
    )

    chat_summary = ChatSummaryPayload(
        session_total=_count(session, select(func.count()).select_from(ChatSession)),
        message_total=_count(session, select(func.count()).select_from(ChatMessage)),
    )

    review_summary = ReviewSummaryPayload(
        open_total=_count(
            session,
            select(func.count()).select_from(ReviewCase).where(ReviewCase.status == "open"),
        )
    )

    agent_summary = AgentSummaryPayload(
        last_24h_total=_count(
            session,
            select(func.count()).select_from(AgentRun).where(AgentRun.created_at >= last_day),
        )
    )

    eval_summary = EvalSummaryPayload(
        last_24h_total=_count(
            session,
            select(func.count()).select_from(EvalRun).where(EvalRun.created_at >= last_day),
        )
    )

    last_hour_logs = list(
        session.execute(select(RuntimeLog).where(RuntimeLog.created_at >= last_hour)).scalars().all()
    )
    request_summary = RequestSummaryPayload(
        last_hour_total=len(last_hour_logs),
        last_hour_error_total=sum(1 for log in last_hour_logs if log.status_code >= 500),
        last_hour_p95_latency_ms=_p95([log.latency_ms for log in last_hour_logs]),
    )

    recent_failed_requests = [
        RecentRequestPayload(
            id=row.id,
            request_id=row.request_id,
            path=row.path,
            status_code=row.status_code,
            created_at=row.created_at,
            error_message=row.error_message,
        )
        for row in session.execute(
            select(RuntimeLog)
            .where(RuntimeLog.status_code >= 500)
            .order_by(RuntimeLog.created_at.desc())
            .limit(5)
        ).scalars()
    ]

    recent_eval_runs = [
        RecentEvalPayload(
            id=row.id,
            dataset_name=row.dataset_name,
            status=row.status,
            created_at=row.created_at,
        )
        for row in session.execute(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(5)).scalars()
    ]

    recent_agent_runs = [
        RecentAgentRunPayload(
            id=row.id,
            agent_name=row.agent_name,
            status=row.status,
            created_at=row.created_at,
        )
        for row in session.execute(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(5)).scalars()
    ]

    return MonitoringOverviewResponse(
        knowledge_summary=knowledge_summary,
        chat_summary=chat_summary,
        review_summary=review_summary,
        agent_summary=agent_summary,
        eval_summary=eval_summary,
        request_summary=request_summary,
        recent_activity=RecentActivityPayload(
            recent_failed_requests=recent_failed_requests,
            recent_eval_runs=recent_eval_runs,
            recent_agent_runs=recent_agent_runs,
        ),
    )
