from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RequestContext, get_request_context
from app.api.guards import require_tenant_match
from app.core.audit import record_audit
from app.core.metrics import observe_agent_run
from app.core.security import AuthContext, require_roles
from app.db.models.agent import AgentRun, AgentThread, AgentThreadCheckpoint, ToolCallLog
from app.db.models.agent_event import AgentEvent
from app.db.models.rule import ReviewCase
from app.db.session import get_session
from app.schemas.agent import (
    AgentCheckpointPayload,
    AgentRunCreateRequest,
    AgentRunListResponse,
    AgentRunPayload,
    AgentRunResumeRequest,
    TimelineStepPayload,
    ToolCallPayload,
)
from app.services.agents.event_sink import persist_agent_events
from app.services.agents.graph import run_agent_workflow
from app.services.agents.router import AgentRouteRequest
from app.services.agents.thread_runtime import (
    build_orchestration_trace,
    build_trace_events,
    persist_execution_checkpoint,
    serialize_checkpoint_summary,
)
from app.services.rules.engine import (
    RuleEvaluationInput,
    create_review_case,
    evaluate_rules,
    infer_city_tier,
    should_create_review_case,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _serialize_checkpoint(
    checkpoint: AgentThreadCheckpoint | None,
) -> AgentCheckpointPayload | None:
    summary = serialize_checkpoint_summary(checkpoint)
    if summary is None:
        return None
    return AgentCheckpointPayload(
        id=str(summary["id"]),
        checkpoint_type=str(summary["checkpoint_type"]),
        status=str(summary["status"]),
        created_at=checkpoint.created_at,
    )


def _resolve_latest_checkpoint(agent_run: AgentRun) -> AgentThreadCheckpoint | None:
    thread = agent_run.thread
    if thread is None or not thread.latest_checkpoint_id:
        return None
    for checkpoint in thread.checkpoints:
        if checkpoint.id == thread.latest_checkpoint_id:
            return checkpoint
    return None


def _load_event_map(session: Session, run_ids: list[str]) -> dict[str, list[AgentEvent]]:
    if not run_ids:
        return {}
    rows = list(
        session.execute(
            select(AgentEvent)
            .where(AgentEvent.agent_run_id.in_(run_ids))
            .order_by(AgentEvent.agent_run_id.asc(), AgentEvent.sequence.asc())
        ).scalars()
    )
    event_map: dict[str, list[AgentEvent]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        event_map.setdefault(row.agent_run_id, []).append(row)
    return event_map


def _serialize_run(
    agent_run: AgentRun,
    *,
    agent_events: list[AgentEvent] | None = None,
) -> AgentRunPayload:
    thread = agent_run.thread
    latest_checkpoint = _resolve_latest_checkpoint(agent_run)
    output = dict(agent_run.output_json or {})
    trace_events = build_trace_events(
        agent_events=agent_events,
        checkpoint=latest_checkpoint,
        pending_interrupt=dict(thread.pending_interrupt_json or {}) if thread is not None else {},
    )
    output["orchestration_trace"] = build_orchestration_trace(
        output=output,
        thread=thread,
        checkpoint=latest_checkpoint,
        agent_name=agent_run.agent_name,
        route_name=agent_run.route_name,
        confidence=agent_run.confidence,
        timeline_nodes=agent_run.timeline_json,
        tool_calls=[
            {
                "tool_name": tool_call.tool_name,
                "status": tool_call.status,
                "latency_ms": tool_call.latency_ms,
            }
            for tool_call in agent_run.tool_calls
        ],
        trace_events=trace_events,
    )
    return AgentRunPayload(
        id=agent_run.id,
        thread_id=agent_run.thread_id,
        agent_name=agent_run.agent_name,
        route_name=agent_run.route_name,
        status=agent_run.status,
        confidence=agent_run.confidence,
        requires_human_review=agent_run.requires_human_review,
        output=output,
        thread_status=thread.status if thread is not None else None,
        pending_interrupt=dict(thread.pending_interrupt_json or {}) if thread is not None else {},
        latest_checkpoint=_serialize_checkpoint(latest_checkpoint),
        timeline=[TimelineStepPayload.model_validate(step) for step in agent_run.timeline_json],
        tool_calls=[
            ToolCallPayload(
                tool_name=tool_call.tool_name,
                status=tool_call.status,
                latency_ms=tool_call.latency_ms,
                input_payload=tool_call.input_json,
                output_payload=tool_call.output_json,
            )
            for tool_call in agent_run.tool_calls
        ],
        created_at=agent_run.created_at,
        updated_at=agent_run.updated_at,
    )


@router.post("/runs", response_model=AgentRunPayload, status_code=status.HTTP_201_CREATED)
async def create_agent_run(
    payload: AgentRunCreateRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> AgentRunPayload:
    """Create an agent run.

    P5.4: promoted to ``async def``. The underlying agent graph is still
    sync internally (engine + tool runner + Milvus client are all sync),
    but running ``run_agent_workflow`` via ``asyncio.to_thread`` frees
    the event loop the same way P4.2 did for chat — concurrent
    ``/api/agents/runs`` requests no longer serialise on a single
    uvicorn worker.
    """
    import asyncio

    request.state.request_id = context.request_id
    # P1.3: enforce tenant_id matches the authenticated claim before doing
    # any work; everything below uses the resolved id.
    tenant_id = require_tenant_match(payload.tenant_id, context)
    request.state.tenant_id = tenant_id
    request.state.customer_id = payload.customer_id
    run_id = str(uuid4())
    thread_id = payload.thread_id or str(uuid4())

    result = await asyncio.to_thread(
        run_agent_workflow,
        AgentRouteRequest(
            question=payload.question,
            tenant_id=tenant_id,
            customer_id=payload.customer_id,
            run_id=run_id,
            thread_id=thread_id,
            user_id=context.user_id,
            ticket=payload.ticket.model_dump() if payload.ticket else None,
        ),
    )

    request.state.session_id = thread_id
    request.state.model_name = result.agent_name
    request.state.token_usage = None
    # P5.2: the token usage sink uses ``agent_name`` to attribute spend
    # per agent flow (policy / anomaly / ticket_router).
    request.state.agent_name = result.agent_name
    output = dict(result.output)

    rule_result = None
    if payload.ticket:
        rule_result = evaluate_rules(
            RuleEvaluationInput(
                amount=payload.ticket.amount,
                city_tier=infer_city_tier(payload.ticket.city),
                expense_type=payload.ticket.expense_type,
            )
        )
        output["rule_result"] = rule_result.as_dict()

    requires_human_review = result.requires_human_review or (
        rule_result is not None and rule_result.decision != "approved"
    )
    run_status = (
        "needs_review" if requires_human_review and result.status == "completed" else result.status
    )
    thread_domain = (
        "ticket"
        if result.route_name == "ticket_triage"
        else "anomaly"
        if result.route_name == "order_anomaly"
        else "policy"
    )

    agent_thread = session.get(AgentThread, thread_id)
    if agent_thread is None:
        agent_thread = AgentThread(
            id=thread_id,
            tenant_id=tenant_id,
            customer_id=payload.customer_id,
            domain=thread_domain,
            specialist=result.agent_name,
            status="awaiting_review" if requires_human_review else "active",
        )
        session.add(agent_thread)
        session.flush()
    else:
        agent_thread.domain = thread_domain
        agent_thread.specialist = result.agent_name
        agent_thread.status = "awaiting_review" if requires_human_review else "active"
        session.add(agent_thread)

    agent_run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        tenant_id=tenant_id,
        customer_id=payload.customer_id,
        agent_name=result.agent_name,
        route_name=result.route_name,
        status=run_status,
        confidence=result.confidence,
        requires_human_review=requires_human_review,
        input_json=payload.model_dump(),
        output_json=dict(output),
        timeline_json=[step.as_dict() for step in result.timeline],
    )
    session.add(agent_run)
    session.flush()

    if result.interrupt is not None:
        agent_thread.pending_interrupt_json = dict(result.interrupt)
    elif not requires_human_review:
        agent_thread.pending_interrupt_json = {}
    agent_thread.memory_summary_json = {
        "last_agent_name": result.agent_name,
        "last_route_name": result.route_name,
        "last_output_preview": str(output)[:400],
        "updated_at": datetime.now(UTC).isoformat(),
    }
    checkpoint = persist_execution_checkpoint(
        session,
        thread=agent_thread,
        agent_run_id=run_id,
        result=result,
        output_override=output,
    )
    output["orchestration_trace"] = build_orchestration_trace(
        result=result,
        output=output,
        thread=agent_thread,
        checkpoint=checkpoint,
    )
    agent_run.output_json = dict(output)
    session.add(agent_run)
    session.add(agent_thread)

    if agent_thread.latest_checkpoint_id:
        checkpoint = session.get(AgentThreadCheckpoint, agent_thread.latest_checkpoint_id)
        if checkpoint is not None and checkpoint.agent_run_id is None:
            checkpoint.agent_run_id = run_id
            session.add(checkpoint)

    for tool_call in result.tool_calls:
        session.add(
            ToolCallLog(
                id=str(uuid4()),
                agent_run_id=run_id,
                tool_name=tool_call.tool_name,
                status=tool_call.status,
                latency_ms=tool_call.latency_ms,
                input_json=tool_call.input_payload,
                output_json=tool_call.output_payload,
            )
        )

    # P3.7: persist structured engine events in the same transaction as the
    # AgentRun row. Non-engine agents (anomaly / ticket_router) produce no
    # events today, so the loop is a no-op for them; once those paths move
    # to the engine this automatically starts populating.
    if result.engine_events:
        persist_agent_events(
            session,
            agent_run_id=run_id,
            tenant_id=tenant_id,
            events=result.engine_events,
        )

    record_audit(
        session,
        request=request,
        ctx=context,
        action="agent.run",
        target_type="AgentRun",
        target_id=run_id,
        payload={
            "agent_name": result.agent_name,
            "route_name": result.route_name,
            "status": run_status,
            "confidence": result.confidence,
            "tool_call_count": len(result.tool_calls),
            "has_ticket": payload.ticket is not None,
            "thread_id": thread_id,
        },
    )
    session.commit()

    if should_create_review_case(
        confidence=result.confidence,
        requires_human_review=requires_human_review,
        rule_result=rule_result,
    ):
        review_case = create_review_case(
            session,
            source="agent",
            tenant_id=tenant_id,
            customer_id=payload.customer_id,
            confidence=result.confidence,
            reason=(
                rule_result.reason
                if rule_result and rule_result.decision != "approved"
                else "命中人工复核条件，已进入审核队列。"
            ),
            payload={
                "agent_name": result.agent_name,
                "agent_run_id": run_id,
                "thread_id": thread_id,
                "interrupt": dict(result.interrupt or {}),
                "question": payload.question,
                "ticket": payload.ticket.model_dump() if payload.ticket else None,
            },
            rule_result=rule_result,
            # P5.4: explicit FK column; payload_json retains the id
            # too during the transition window.
            agent_run_id=run_id,
        )
        output["review_case_id"] = review_case.id
        agent_run.output_json = dict(output)
        agent_run.status = "needs_review"
        agent_run.requires_human_review = True
        session.add(agent_run)
        session.commit()

    observe_agent_run(result.agent_name, agent_run.status)
    session.refresh(agent_run)
    agent_run = session.execute(
        select(AgentRun)
        .options(
            selectinload(AgentRun.tool_calls),
            selectinload(AgentRun.thread).selectinload(AgentThread.checkpoints),
        )
        .where(AgentRun.id == run_id)
    ).scalar_one()
    event_map = _load_event_map(session, [run_id])
    return _serialize_run(agent_run, agent_events=event_map.get(run_id, []))


def _next_event_sequence(session: Session, agent_run_id: str) -> int:
    """Return the next ``sequence`` number for a new event on this run.

    ``agent_event`` is append-only; picking ``MAX(sequence) + 1`` keeps
    the resume event after every node's NODE_END without having to
    replay the engine. Empty history starts at 0 (unusual but defensible).
    """
    row = session.execute(
        select(AgentEvent.sequence)
        .where(AgentEvent.agent_run_id == agent_run_id)
        .order_by(AgentEvent.sequence.desc())
        .limit(1)
    ).first()
    if row is None:
        return 0
    return int(row[0]) + 1


@router.post(
    "/runs/{run_id}/resume",
    response_model=AgentRunPayload,
)
def resume_agent_run(
    run_id: str,
    payload: AgentRunResumeRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "reviewer")),
    session: Session = Depends(get_session),
) -> AgentRunPayload:
    """HITL resume (P3.8).

    A paused run lands in ``awaiting_review`` when ``requires_human_review``
    is set. This endpoint is the terminal transition: a reviewer picks
    approve / reject, and we:

    1. Update ``AgentRun.status`` accordingly (``completed`` / ``rejected``).
    2. Append a ``RESUME`` event to ``agent_event`` with the decision,
       so the structured timeline reflects the human action.
    3. If a ``ReviewCase`` was created for this run, mark it resolved.
    4. Emit an audit row scoped to the reviewer's identity.

    We do NOT re-execute the graph from the checkpoint -- the current
    agents synthesize a full answer before pausing, so the reviewer's
    decision IS the final outcome. Full graph-state resume is tracked as
    a follow-on (see ``docs/plans/2026-04-22-phase-3-agent-revamp.md``).
    """
    request.state.request_id = context.request_id
    agent_run = session.get(AgentRun, run_id)
    if agent_run is None:
        raise HTTPException(status_code=404, detail="agent run not found")

    # Tenant guard: a reviewer for tenant A cannot resolve a run from B.
    require_tenant_match(agent_run.tenant_id, context)
    request.state.tenant_id = agent_run.tenant_id
    request.state.customer_id = agent_run.customer_id

    if agent_run.status not in ("awaiting_review", "needs_review"):
        raise HTTPException(
            status_code=409,
            detail=f"agent run is in status {agent_run.status!r}, not resumable",
        )

    new_status = "completed" if payload.decision in {"approve", "edit"} else "rejected"
    agent_run.status = new_status
    agent_run.requires_human_review = False
    output = dict(agent_run.output_json)
    if payload.decision == "edit":
        if not payload.edited_answer:
            raise HTTPException(status_code=422, detail="edited_answer is required for edit")
        output["answer"] = payload.edited_answer
    output["resolution"] = {
        "decision": payload.decision,
        "note": payload.note,
        "resolved_by": context.user_id,
        "resolved_at": datetime.now(UTC).isoformat(),
    }
    agent_run.output_json = output
    session.add(agent_run)
    session.flush()

    thread = session.get(AgentThread, agent_run.thread_id)
    if thread is not None:
        thread.status = "active" if payload.decision in {"approve", "edit"} else "rejected"
        thread.pending_interrupt_json = {}
        session.add(thread)

    # Append structured RESUME event so ``agent_event`` is the source of
    # truth for the whole lifecycle.
    resume_event = AgentEvent(
        id=str(uuid4()),
        agent_run_id=agent_run.id,
        sequence=_next_event_sequence(session, agent_run.id),
        event_type="RESUME",
        node_name="human_review_checkpoint",
        payload_json={
            "decision": payload.decision,
            "note": payload.note,
            "resolved_by": context.user_id,
        },
        tenant_id=agent_run.tenant_id,
    )
    session.add(resume_event)

    # P5.4: ``ReviewCase.agent_run_id`` is now an explicit FK column,
    # so the JOIN is a single SQL WHERE. The old ``payload_json``
    # fallback is kept for rows created before the migration ran.
    linked_cases = list(
        session.execute(
            select(ReviewCase).where(
                ReviewCase.tenant_id == agent_run.tenant_id,
                ReviewCase.status == "open",
                ReviewCase.agent_run_id == agent_run.id,
            )
        ).scalars()
    )
    if not linked_cases:
        # Deprecation window: fall back to the Python filter for rows
        # whose ``agent_run_id`` wasn't backfilled.
        candidate_cases = list(
            session.execute(
                select(ReviewCase).where(
                    ReviewCase.tenant_id == agent_run.tenant_id,
                    ReviewCase.status == "open",
                )
            ).scalars()
        )
        linked_cases = [
            case
            for case in candidate_cases
            if (case.payload_json or {}).get("agent_run_id") == agent_run.id
        ]
    for case in linked_cases:
        case.status = "resolved" if payload.decision in {"approve", "edit"} else "rejected"
        case.resolved_by = context.user_id
        case.resolution_note = payload.note
        session.add(case)

    record_audit(
        session,
        request=request,
        ctx=context,
        action="agent.resume",
        target_type="AgentRun",
        target_id=agent_run.id,
        payload={
            "decision": payload.decision,
            "note": payload.note,
            "previous_status": "awaiting_review",
            "new_status": new_status,
        },
    )
    session.commit()

    observe_agent_run(agent_run.agent_name, new_status)
    agent_run = session.execute(
        select(AgentRun)
        .options(
            selectinload(AgentRun.tool_calls),
            selectinload(AgentRun.thread).selectinload(AgentThread.checkpoints),
        )
        .where(AgentRun.id == run_id)
    ).scalar_one()
    event_map = _load_event_map(session, [run_id])
    return _serialize_run(agent_run, agent_events=event_map.get(run_id, []))


@router.get("/runs", response_model=AgentRunListResponse)
def list_agent_runs(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> AgentRunListResponse:
    rows = list(
        session.execute(
            select(AgentRun)
            .options(
                selectinload(AgentRun.tool_calls),
                selectinload(AgentRun.thread).selectinload(AgentThread.checkpoints),
            )
            .order_by(AgentRun.created_at.desc())
        ).scalars()
    )
    event_map = _load_event_map(session, [row.id for row in rows])
    return AgentRunListResponse(
        items=[_serialize_run(row, agent_events=event_map.get(row.id, [])) for row in rows]
    )
