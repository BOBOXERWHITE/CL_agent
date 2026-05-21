from __future__ import annotations

from app.services.agents.policy_domain import choose_policy_specialist
from app.services.agents.policy_profiles import get_policy_profile, match_policy_profile


def test_policy_domain_router_prefers_flight_specialist() -> None:
    decision = choose_policy_specialist("国内出差想预订 business class，还需要审批吗？")
    assert decision.domain == "flight"
    assert decision.specialist == "flight_policy_agent"
    assert decision.confidence > 0.8


def test_policy_domain_router_prefers_reimbursement_specialist() -> None:
    decision = choose_policy_specialist("这张报销单的发票抬头、税号和进项税应该怎么处理？")
    assert decision.domain == "reimbursement"
    assert decision.specialist == "reimbursement_policy_agent"
    assert decision.confidence > 0.8


def test_hotel_profile_keeps_priority_over_reimbursement_terms() -> None:
    profile = match_policy_profile("北京酒店含早，发票抬头和税号都齐全，这单怎么报销？")
    assert profile is not None
    assert profile.domain == "hotel"


def test_flight_profile_expands_required_dimensions() -> None:
    profile = get_policy_profile("flight")
    assert profile is not None
    question = "国内出差预订商务舱并且需要改签，必须走 OBT 吗？"
    facts = profile.extract_facts(question)
    dimensions = profile.required_dimensions(question, facts)

    assert dimensions == [
        "cabin_policy",
        "approval_requirement",
        "change_refund_policy",
        "booking_channel_compliance",
    ]
    subquestions = profile.build_subquestions(question, facts, dimensions)
    assert subquestions[0]["dimension"] == "primary"
    assert len(subquestions) == len(dimensions) + 1


def test_reimbursement_profile_expands_required_dimensions() -> None:
    profile = get_policy_profile("reimbursement")
    assert profile is not None
    question = "这张报销单有发票抬头和税号，还涉及餐补、例外审批和行程单缺失。"
    facts = profile.extract_facts(question)
    dimensions = profile.required_dimensions(question, facts)

    assert dimensions == [
        "invoice_tax",
        "approval_requirement",
        "allowance_policy",
        "supporting_documents",
    ]
    subquestions = profile.build_subquestions(question, facts, dimensions)
    assert subquestions[0]["dimension"] == "primary"
    assert len(subquestions) == len(dimensions) + 1
