from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.api.guards import require_tenant_match
from app.core.audit import record_audit
from app.core.security import AuthContext, require_roles
from app.db.models.agent import AgentThread, AgentThreadCheckpoint
from app.db.models.agent_event import AgentEvent
from app.db.models.rule import ReviewCase
from app.db.session import get_session
from app.schemas.rule import ReviewCaseListResponse, ReviewCasePayload, ReviewIngestRequest
from app.services.agents.thread_runtime import build_trace_events
from app.services.rules.engine import RuleEvaluationResult, create_review_case

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _serialize_checkpoint_summary(
    checkpoint: AgentThreadCheckpoint | None,
) -> dict[str, object] | None:
    if checkpoint is None:
        return None
    return {
        "id": checkpoint.id,
        "checkpoint_type": checkpoint.checkpoint_type,
        "status": checkpoint.status,
        "created_at": checkpoint.created_at,
    }


def _serialize_review_case(
    review_case: ReviewCase,
    *,
    thread_by_id: dict[str, AgentThread] | None = None,
    checkpoint_by_id: dict[str, AgentThreadCheckpoint] | None = None,
    event_by_run_id: dict[str, list[AgentEvent]] | None = None,
) -> ReviewCasePayload:
    payload = dict(review_case.payload_json or {})
    thread_id = payload.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        thread_id = None
    thread = thread_by_id.get(thread_id) if thread_by_id and thread_id else None
    agent_run_id = review_case.agent_run_id
    if agent_run_id is None:
        legacy_agent_run_id = payload.get("agent_run_id")
        if isinstance(legacy_agent_run_id, str) and legacy_agent_run_id.strip():
            agent_run_id = legacy_agent_run_id
    latest_checkpoint = None
    if thread is not None and checkpoint_by_id and thread.latest_checkpoint_id:
        latest_checkpoint = checkpoint_by_id.get(thread.latest_checkpoint_id)
    pending_interrupt = (
        dict(thread.pending_interrupt_json or {})
        if thread is not None
        else dict(payload.get("interrupt") or {})
    )
    trace_events = build_trace_events(
        agent_events=event_by_run_id.get(agent_run_id, [])
        if event_by_run_id and agent_run_id
        else [],
        checkpoint=latest_checkpoint,
        pending_interrupt=pending_interrupt,
        review_case=review_case,
    )
    return ReviewCasePayload(
        id=review_case.id,
        source=review_case.source,
        tenant_id=review_case.tenant_id,
        customer_id=review_case.customer_id,
        agent_run_id=agent_run_id,
        thread_id=thread_id,
        status=review_case.status,
        confidence=review_case.confidence,
        reason=review_case.reason,
        suggested_action=review_case.suggested_action,
        payload=payload,
        rule_result=review_case.rule_result_json,
        pending_interrupt=pending_interrupt,
        latest_checkpoint=_serialize_checkpoint_summary(latest_checkpoint),
        trace_events=trace_events,
        created_at=review_case.created_at,
        updated_at=review_case.updated_at,
    )


@router.post("/ingest", response_model=ReviewCasePayload, status_code=status.HTTP_201_CREATED)
def ingest_review_case(
    payload: ReviewIngestRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> ReviewCasePayload:
    # P1.3: enforce body-supplied tenant_id matches the JWT claim.
    tenant_id = require_tenant_match(payload.tenant_id, context)
    rule_result = None
    if payload.rule_result:
        rule_result = RuleEvaluationResult(
            decision=str(payload.rule_result.get("decision", "approved")),
            reason=str(payload.rule_result.get("reason", "")),
            suggested_action=str(payload.rule_result.get("suggested_action", "转人工复核")),
            rule_hits=[],
        )
    review_case = create_review_case(
        session,
        source=payload.source,
        tenant_id=tenant_id,
        customer_id=payload.customer_id,
        confidence=payload.confidence,
        reason=payload.reason or "命中人工复核条件。",
        payload=payload.payload,
        rule_result=rule_result,
    )
    record_audit(
        session,
        request=request,
        ctx=context,
        action="review.ingest",
        target_type="ReviewCase",
        target_id=review_case.id,
        payload={
            "source": payload.source,
            "confidence": payload.confidence,
            "decision": rule_result.decision if rule_result else None,
        },
    )
    session.commit()
    return _serialize_review_case(review_case)


@router.get("/queue", response_model=ReviewCaseListResponse)
def list_review_queue(
    _: AuthContext = Depends(require_roles("admin", "reviewer")),
    session: Session = Depends(get_session),
) -> ReviewCaseListResponse:
    rows = list(
        session.execute(
            select(ReviewCase)
            .where(ReviewCase.status == "open")
            .order_by(ReviewCase.created_at.desc())
        ).scalars()
    )
    thread_ids = sorted(
        {
            str((row.payload_json or {}).get("thread_id")).strip()
            for row in rows
            if isinstance((row.payload_json or {}).get("thread_id"), str)
            and str((row.payload_json or {}).get("thread_id")).strip()
        }
    )
    thread_by_id: dict[str, AgentThread] = {}
    checkpoint_by_id: dict[str, AgentThreadCheckpoint] = {}
    event_by_run_id: dict[str, list[AgentEvent]] = {}
    if thread_ids:
        threads = list(
            session.execute(select(AgentThread).where(AgentThread.id.in_(thread_ids))).scalars()
        )
        thread_by_id = {thread.id: thread for thread in threads}
        checkpoint_ids = sorted(
            {
                thread.latest_checkpoint_id
                for thread in threads
                if isinstance(thread.latest_checkpoint_id, str) and thread.latest_checkpoint_id
            }
        )
        if checkpoint_ids:
            checkpoints = list(
                session.execute(
                    select(AgentThreadCheckpoint).where(
                        AgentThreadCheckpoint.id.in_(checkpoint_ids)
                    )
                ).scalars()
            )
            checkpoint_by_id = {checkpoint.id: checkpoint for checkpoint in checkpoints}
    agent_run_ids = sorted(
        {
            review_case.agent_run_id
            for review_case in rows
            if isinstance(review_case.agent_run_id, str) and review_case.agent_run_id
        }
    )
    if agent_run_ids:
        event_rows = list(
            session.execute(
                select(AgentEvent)
                .where(AgentEvent.agent_run_id.in_(agent_run_ids))
                .order_by(AgentEvent.agent_run_id.asc(), AgentEvent.sequence.asc())
            ).scalars()
        )
        event_by_run_id = {run_id: [] for run_id in agent_run_ids}
        for event in event_rows:
            event_by_run_id.setdefault(event.agent_run_id, []).append(event)
    return ReviewCaseListResponse(
        items=[
            _serialize_review_case(
                row,
                thread_by_id=thread_by_id,
                checkpoint_by_id=checkpoint_by_id,
                event_by_run_id=event_by_run_id,
            )
            for row in rows
        ]
    )
