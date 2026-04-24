from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthContext, require_roles
from app.db.models.rule import PolicyRule
from app.db.session import get_session
from app.schemas.rule import (
    PolicyRuleListResponse,
    PolicyRulePayload,
    RuleEvaluationRequest,
    RuleEvaluationResponse,
    RuleHitPayload,
)
from app.services.rules.engine import RuleEvaluationInput, evaluate_rules

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("", response_model=PolicyRuleListResponse)
def list_rules(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> PolicyRuleListResponse:
    rows = session.execute(select(PolicyRule).order_by(PolicyRule.rule_code.asc())).scalars()
    return PolicyRuleListResponse(
        items=[
            PolicyRulePayload(
                id=row.id,
                rule_code=row.rule_code,
                expense_type=row.expense_type,
                city_tier=row.city_tier,
                threshold_amount=row.threshold_amount,
                decision_on_exceed=row.decision_on_exceed,
                description=row.description,
                enabled=row.enabled,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
    )


@router.post("/evaluate", response_model=RuleEvaluationResponse)
def evaluate_rule_payload(
    payload: RuleEvaluationRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> RuleEvaluationResponse:
    result = evaluate_rules(
        RuleEvaluationInput(
            amount=payload.amount,
            city_tier=payload.city_tier,
            expense_type=payload.expense_type,
        )
    )
    return RuleEvaluationResponse(
        decision=result.decision,
        reason=result.reason,
        suggested_action=result.suggested_action,
        rule_hits=[
            RuleHitPayload.model_validate(rule_hit.as_dict()) for rule_hit in result.rule_hits
        ],
    )
