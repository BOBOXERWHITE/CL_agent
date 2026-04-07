from __future__ import annotations

from dataclasses import dataclass
from typing import Any


POLICY_KEYWORDS = (
    "政策",
    "报销",
    "酒店",
    "住宿",
    "机票",
    "舱位",
    "差旅",
    "business class",
    "economy class",
)

TICKET_KEYWORDS = (
    "工单",
    "报销单",
    "排队",
    "拦截",
    "审批",
    "ticket",
)

ANOMALY_KEYWORDS = (
    "异常订单",
    "重复预订",
    "重复下单",
    "duplicate booking",
)


@dataclass(frozen=True)
class AgentRouteRequest:
    question: str
    tenant_id: str
    customer_id: str
    ticket: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentRouteDecision:
    agent_name: str
    route_name: str
    reason: str
    requires_human_review: bool


def choose_route(request: AgentRouteRequest) -> AgentRouteDecision:
    normalized_question = request.question.lower()

    if request.ticket is not None or any(keyword in normalized_question for keyword in TICKET_KEYWORDS):
        return AgentRouteDecision(
            agent_name="ticket_router_agent",
            route_name="ticket_triage",
            reason="检测到工单或审核排队语义，转入工单分流 Agent。",
            requires_human_review=True,
        )

    if any(keyword in normalized_question for keyword in ANOMALY_KEYWORDS):
        return AgentRouteDecision(
            agent_name="order_anomaly_agent",
            route_name="order_anomaly",
            reason="检测到订单异常语义，转入异常订单 Agent。",
            requires_human_review=True,
        )

    if any(keyword in normalized_question for keyword in POLICY_KEYWORDS):
        return AgentRouteDecision(
            agent_name="travel_policy_agent",
            route_name="policy_qa",
            reason="检测到政策问答语义，转入政策问答 Agent。",
            requires_human_review=False,
        )

    return AgentRouteDecision(
        agent_name="travel_policy_agent",
        route_name="policy_qa",
        reason="未命中特殊流程，默认走政策问答 Agent。",
        requires_human_review=False,
    )
