from __future__ import annotations

from app.services.agents.router import AgentRouteRequest, choose_route


def test_router_sends_policy_question_to_rag_agent() -> None:
    route = choose_route(
        AgentRouteRequest(
            question="北京酒店报销上限是多少？",
            tenant_id="t1",
            customer_id="c1",
        )
    )

    assert route.agent_name == "travel_policy_agent"
    assert route.route_name == "policy_qa"
    assert route.requires_human_review is False


def test_router_sends_ticket_payload_to_ticket_router_agent() -> None:
    route = choose_route(
        AgentRouteRequest(
            question="这张报销单为什么被拦截？",
            tenant_id="t1",
            customer_id="c1",
            ticket={
                "ticket_id": "ticket-001",
                "expense_type": "hotel",
                "city": "北京",
                "amount": 1200,
                "status": "pending_review",
            },
        )
    )

    assert route.agent_name == "ticket_router_agent"
    assert route.route_name == "ticket_triage"
    assert route.requires_human_review is True
