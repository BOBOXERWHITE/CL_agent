from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.api.guards import require_tenant_match
from app.core.audit import record_audit
from app.core.security import AuthContext, require_roles
from app.db.models.rule import ReviewCase
from app.db.session import get_session
from app.schemas.rule import ReviewCaseListResponse, ReviewCasePayload, ReviewIngestRequest
from app.services.rules.engine import RuleEvaluationResult, create_review_case

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _serialize_review_case(review_case: ReviewCase) -> ReviewCasePayload:
    return ReviewCasePayload(
        id=review_case.id,
        source=review_case.source,
        tenant_id=review_case.tenant_id,
        customer_id=review_case.customer_id,
        status=review_case.status,
        confidence=review_case.confidence,
        reason=review_case.reason,
        suggested_action=review_case.suggested_action,
        payload=review_case.payload_json,
        rule_result=review_case.rule_result_json,
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
    rows = session.execute(
        select(ReviewCase).where(ReviewCase.status == "open").order_by(ReviewCase.created_at.desc())
    ).scalars()
    return ReviewCaseListResponse(items=[_serialize_review_case(row) for row in rows])
