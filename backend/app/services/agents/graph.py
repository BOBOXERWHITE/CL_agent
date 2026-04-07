from __future__ import annotations

from app.services.agents.anomaly_graph import execute_anomaly_graph
from app.services.agents.nodes import append_timeline_step
from app.services.agents.policy_graph import execute_policy_graph
from app.services.agents.router import AgentRouteRequest, choose_route
from app.services.agents.state import AgentExecutionResult, TimelineStep
from app.services.agents.ticket_router_graph import execute_ticket_router_graph


def run_agent_workflow(request: AgentRouteRequest) -> AgentExecutionResult:
    route = choose_route(request)
    timeline: list[TimelineStep] = []
    append_timeline_step(
        timeline,
        node_name="router",
        status="completed",
        detail=route.reason,
    )

    if route.agent_name == "ticket_router_agent":
        return execute_ticket_router_graph(
            question=request.question,
            ticket=request.ticket or {},
            route_name=route.route_name,
            base_timeline=timeline,
        )

    if route.agent_name == "order_anomaly_agent":
        return execute_anomaly_graph(
            question=request.question,
            route_name=route.route_name,
            base_timeline=timeline,
        )

    return execute_policy_graph(
        question=request.question,
        tenant_id=request.tenant_id,
        customer_id=request.customer_id,
        route_name=route.route_name,
        base_timeline=timeline,
    )
