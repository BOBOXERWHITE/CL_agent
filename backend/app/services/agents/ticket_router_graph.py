from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agents.nodes import append_timeline_step, invoke_tool
from app.services.agents.state import AgentExecutionResult, TimelineStep, ToolCallRecord
from app.services.agents.tools import lookup_order_details, lookup_ticket_queue


@dataclass(frozen=True)
class TicketRoutingResult:
    queue_name: str
    reason: str
    tool_calls: list[ToolCallRecord]


def run_ticket_router(ticket: dict[str, Any]) -> TicketRoutingResult:
    queue_lookup_call = invoke_tool(
        tool_name="ticket_queue_lookup",
        tool_input={"ticket": ticket},
        handler=lookup_ticket_queue,
    )
    order_lookup_call = invoke_tool(
        tool_name="order_lookup",
        tool_input={"ticket_id": str(ticket.get("ticket_id", ""))},
        handler=lookup_order_details,
    )
    return TicketRoutingResult(
        queue_name=str(queue_lookup_call.output_payload["queue_name"]),
        reason=str(queue_lookup_call.output_payload["reason"]),
        tool_calls=[queue_lookup_call, order_lookup_call],
    )


def execute_ticket_router_graph(
    *,
    question: str,
    ticket: dict[str, Any],
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    timeline = list(base_timeline)
    append_timeline_step(
        timeline,
        node_name="ticket_triage",
        status="completed",
        detail="已完成工单分流预判。",
    )
    result = run_ticket_router(ticket)
    append_timeline_step(
        timeline,
        node_name="ticket_queue_lookup",
        status="completed",
        detail=result.reason,
    )
    append_timeline_step(
        timeline,
        node_name="order_lookup",
        status="completed",
        detail=f"已查询关联订单，问题摘要：{question}",
    )
    append_timeline_step(
        timeline,
        node_name="human_review_checkpoint",
        status="required",
        detail="工单需要进入人工处理队列。",
    )
    return AgentExecutionResult(
        agent_name="ticket_router_agent",
        route_name=route_name,
        status="completed",
        confidence=0.86,
        requires_human_review=True,
        output={
            "queue_name": result.queue_name,
            "reason": result.reason,
        },
        timeline=timeline,
        tool_calls=result.tool_calls,
    )
