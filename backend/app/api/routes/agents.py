from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RequestContext, get_request_context
from app.core.metrics import observe_agent_run
from app.core.security import AuthContext, require_roles
from app.db.models.agent import AgentRun, ToolCallLog
from app.db.session import get_session, init_db
from app.schemas.agent import AgentRunCreateRequest, AgentRunListResponse, AgentRunPayload, ToolCallPayload, TimelineStepPayload
from app.services.agents.graph import run_agent_workflow
from app.services.agents.router import AgentRouteRequest
from app.services.rules.engine import (
    RuleEvaluationInput,
    create_review_case,
    evaluate_rules,
    infer_city_tier,
    seed_default_rules,
    should_create_review_case,
)


router = APIRouter(prefix="/api/agents", tags=["agents"])


def _serialize_run(agent_run: AgentRun) -> AgentRunPayload:
    return AgentRunPayload(
        id=agent_run.id,
        agent_name=agent_run.agent_name,
        route_name=agent_run.route_name,
        status=agent_run.status,
        confidence=agent_run.confidence,
        requires_human_review=agent_run.requires_human_review,
        output=agent_run.output_json,
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
def create_agent_run(
    payload: AgentRunCreateRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> AgentRunPayload:
    init_db()
    seed_default_rules(session)
    request.state.request_id = context.request_id
    request.state.tenant_id = payload.tenant_id
    request.state.customer_id = payload.customer_id

    result = run_agent_workflow(
        AgentRouteRequest(
            question=payload.question,
            tenant_id=payload.tenant_id,
            customer_id=payload.customer_id,
            ticket=payload.ticket.model_dump() if payload.ticket else None,
        )
    )

    run_id = str(uuid4())
    request.state.session_id = run_id
    request.state.model_name = result.agent_name
    request.state.token_usage = None
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
    run_status = "needs_review" if requires_human_review and result.status == "completed" else result.status

    agent_run = AgentRun(
        id=run_id,
        tenant_id=payload.tenant_id,
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

    session.commit()

    if should_create_review_case(
        confidence=result.confidence,
        requires_human_review=requires_human_review,
        rule_result=rule_result,
    ):
        review_case = create_review_case(
            session,
            source="agent",
            tenant_id=payload.tenant_id,
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
                "question": payload.question,
                "ticket": payload.ticket.model_dump() if payload.ticket else None,
            },
            rule_result=rule_result,
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
        .options(selectinload(AgentRun.tool_calls))
        .where(AgentRun.id == run_id)
    ).scalar_one()
    return _serialize_run(agent_run)


@router.get("/runs", response_model=AgentRunListResponse)
def list_agent_runs(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> AgentRunListResponse:
    init_db()
    rows = session.execute(
        select(AgentRun)
        .options(selectinload(AgentRun.tool_calls))
        .order_by(AgentRun.created_at.desc())
    ).scalars()
    return AgentRunListResponse(items=[_serialize_run(row) for row in rows])
