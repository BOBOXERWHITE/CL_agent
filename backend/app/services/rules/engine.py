from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.rule import PolicyRule, ReviewCase


DEFAULT_RULES = (
    {
        "rule_code": "hotel_amount_tier_1",
        "expense_type": "hotel",
        "city_tier": "tier-1",
        "threshold_amount": 1000.0,
        "decision_on_exceed": "blocked",
        "description": "一线城市酒店报销上限为 1000。",
    },
    {
        "rule_code": "hotel_amount_tier_2",
        "expense_type": "hotel",
        "city_tier": "tier-2",
        "threshold_amount": 800.0,
        "decision_on_exceed": "blocked",
        "description": "二线城市酒店报销上限为 800。",
    },
    {
        "rule_code": "hotel_amount_tier_3",
        "expense_type": "hotel",
        "city_tier": "tier-3",
        "threshold_amount": 600.0,
        "decision_on_exceed": "blocked",
        "description": "三线城市酒店报销上限为 600。",
    },
)

CITY_TIER_MAP = {
    "北京": "tier-1",
    "上海": "tier-1",
    "广州": "tier-1",
    "深圳": "tier-1",
    "杭州": "tier-2",
    "成都": "tier-2",
    "南京": "tier-2",
}


@dataclass(frozen=True)
class RuleEvaluationInput:
    amount: float
    city_tier: str
    expense_type: str


@dataclass(frozen=True)
class RuleHit:
    rule_code: str
    decision: str
    threshold_amount: float
    actual_amount: float
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "rule_code": self.rule_code,
            "decision": self.decision,
            "threshold_amount": self.threshold_amount,
            "actual_amount": self.actual_amount,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuleEvaluationResult:
    decision: str
    reason: str
    suggested_action: str
    rule_hits: list[RuleHit]

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
            "rule_hits": [rule_hit.as_dict() for rule_hit in self.rule_hits],
        }


def infer_city_tier(city: str) -> str:
    return CITY_TIER_MAP.get(city, "tier-2")


def seed_default_rules(session: Session) -> list[PolicyRule]:
    existing_rules = session.execute(select(PolicyRule)).scalars().all()
    if existing_rules:
        return existing_rules

    created_rules: list[PolicyRule] = []
    for rule in DEFAULT_RULES:
        created_rule = PolicyRule(
            id=str(uuid4()),
            rule_code=rule["rule_code"],
            expense_type=rule["expense_type"],
            city_tier=rule["city_tier"],
            threshold_amount=rule["threshold_amount"],
            decision_on_exceed=rule["decision_on_exceed"],
            description=rule["description"],
            enabled=True,
            metadata_json={},
        )
        session.add(created_rule)
        created_rules.append(created_rule)
    session.commit()
    return created_rules


def evaluate_rules(rule_input: RuleEvaluationInput) -> RuleEvaluationResult:
    matches: list[RuleHit] = []
    for rule in DEFAULT_RULES:
        if rule["expense_type"] != rule_input.expense_type:
            continue
        if rule["city_tier"] != rule_input.city_tier:
            continue
        if rule_input.amount <= float(rule["threshold_amount"]):
            continue
        matches.append(
            RuleHit(
                rule_code=str(rule["rule_code"]),
                decision=str(rule["decision_on_exceed"]),
                threshold_amount=float(rule["threshold_amount"]),
                actual_amount=rule_input.amount,
                reason=f"超出酒店标准：当前金额 {rule_input.amount:.0f}，阈值 {float(rule['threshold_amount']):.0f}。",
            )
        )

    if matches:
        return RuleEvaluationResult(
            decision="blocked",
            reason=matches[0].reason,
            suggested_action="转人工复核",
            rule_hits=matches,
        )

    return RuleEvaluationResult(
        decision="approved",
        reason="未命中阻断规则。",
        suggested_action="允许继续流转",
        rule_hits=[],
    )


def create_review_case(
    session: Session,
    *,
    source: str,
    tenant_id: str,
    customer_id: str,
    confidence: float,
    reason: str,
    payload: dict[str, object],
    rule_result: RuleEvaluationResult | None = None,
) -> ReviewCase:
    review_case = ReviewCase(
        id=str(uuid4()),
        source=source,
        tenant_id=tenant_id,
        customer_id=customer_id,
        status="open",
        confidence=confidence,
        reason=reason,
        suggested_action="转人工复核",
        payload_json=payload,
        rule_result_json=rule_result.as_dict() if rule_result else {},
    )
    session.add(review_case)
    session.commit()
    session.refresh(review_case)
    return review_case


def should_create_review_case(
    *,
    confidence: float,
    requires_human_review: bool,
    rule_result: RuleEvaluationResult | None = None,
) -> bool:
    if requires_human_review:
        return True
    if confidence < 0.6:
        return True
    if rule_result and rule_result.decision != "approved":
        return True
    return False
