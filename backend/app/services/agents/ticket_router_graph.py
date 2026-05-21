"""Ticket router agent — engine-migrated in P5.3.

Pre-Phase-5 this file ran two sequential tool calls inside a single
function and emitted a constant confidence=0.86. P5.3 wraps the same
two calls in the P3.1 engine so every run produces structured
``agent_event`` rows (same observability surface as policy / anomaly).

Engine shape
------------

    queue_lookup  ─▶  order_lookup  ─▶  finalize

- ``queue_lookup``: resolve which operator queue handles this ticket
  category. Result lives in ``scratchpad.queue`` + a ``ToolCallRecord``
  row for the legacy timeline.
- ``order_lookup``: fetch the canonical order snapshot so the reviewer
  has context. Same shape.
- ``finalize``: write the routing decision into ``scratchpad.final``.

The two tool calls are inherently sequential (order lookup is just
context enrichment on top of the queue decision); running them in
parallel would only shave ~10ms and complicate the state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agents.engine import (
    Graph,
    GraphRunResult,
    GraphState,
    NodeResult,
)
from app.services.agents.nodes import append_timeline_step, invoke_tool
from app.services.agents.state import AgentExecutionResult, TimelineStep, ToolCallRecord
from app.services.agents.tools import lookup_order_details, lookup_ticket_queue


@dataclass(frozen=True)
class TicketRoutingResult:
    queue_name: str
    reason: str
    tool_calls: list[ToolCallRecord]


# ---------------------------------------------------------------------------
# Legacy helper — still exported because other callers (tests, scripts)
# import it directly to drive the two tool calls without a full graph run.
# ---------------------------------------------------------------------------


def run_ticket_router(ticket: dict[str, Any]) -> TicketRoutingResult:
    """Run the two tool calls eagerly (no engine). Kept for callers
    that predate P5.3 and don't want a ``GraphState``.
    """
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


# ---------------------------------------------------------------------------
# Engine nodes
# ---------------------------------------------------------------------------


def _queue_lookup_node(state: GraphState) -> NodeResult:
    ticket = state.scratchpad.get("ticket") or {}
    call = invoke_tool(
        tool_name="ticket_queue_lookup",
        tool_input={"ticket": ticket},
        handler=lookup_ticket_queue,
    )
    return NodeResult(
        next_node="order_lookup",
        state_delta={
            "scratchpad": {
                "queue_name": str(call.output_payload["queue_name"]),
                "queue_reason": str(call.output_payload["reason"]),
            },
            "tool_calls": [_tool_call_to_dict(call)],
        },
    )


def _order_lookup_node(state: GraphState) -> NodeResult:
    ticket = state.scratchpad.get("ticket") or {}
    call = invoke_tool(
        tool_name="order_lookup",
        tool_input={"ticket_id": str(ticket.get("ticket_id", ""))},
        handler=lookup_order_details,
    )
    return NodeResult(
        next_node="finalize",
        state_delta={
            "scratchpad": {"order_snapshot": dict(call.output_payload)},
            "tool_calls": [_tool_call_to_dict(call)],
        },
    )


def _finalize_node(state: GraphState) -> NodeResult:
    scratchpad = state.scratchpad
    final = {
        "queue_name": scratchpad.get("queue_name", "ops-general"),
        "reason": scratchpad.get("queue_reason", ""),
        "order_snapshot": scratchpad.get("order_snapshot", {}),
    }
    return NodeResult(next_node=None, state_delta={"scratchpad": {"final": final}})


def build_ticket_router_graph() -> Graph:
    return Graph(
        nodes={
            "queue_lookup": _queue_lookup_node,
            "order_lookup": _order_lookup_node,
            "finalize": _finalize_node,
        },
        entry="queue_lookup",
    )


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def _tool_call_to_dict(record: ToolCallRecord) -> dict[str, Any]:
    return {
        "tool_name": record.tool_name,
        "status": record.status,
        "latency_ms": record.latency_ms,
        "input_payload": record.input_payload,
        "output_payload": record.output_payload,
    }


def _collect_tool_call_records(state: GraphState) -> list[ToolCallRecord]:
    return [
        ToolCallRecord(
            tool_name=entry.get("tool_name", ""),
            status=entry.get("status", ""),
            latency_ms=int(entry.get("latency_ms", 0)),
            input_payload=entry.get("input_payload", {}) or {},
            output_payload=entry.get("output_payload", {}) or {},
        )
        for entry in state.tool_calls
    ]


def _run_result_to_execution(
    run_result: GraphRunResult,
    *,
    question: str,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    final = run_result.state.scratchpad.get("final") or {}
    queue_name = str(final.get("queue_name", "ops-general"))
    reason = str(final.get("reason", ""))
    tool_calls = _collect_tool_call_records(run_result.state)

    timeline = list(base_timeline)
    append_timeline_step(
        timeline,
        node_name="ticket_triage",
        status="completed",
        detail="已完成工单分流预判。",
    )
    append_timeline_step(
        timeline,
        node_name="ticket_queue_lookup",
        status="completed",
        detail=reason,
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

    interrupt = {
        "kind": "human_review",
        "reason": "ticket routing requires operator review",
        "queue_name": queue_name,
        "allowed_decisions": ["approve", "edit", "reject"],
    }

    return AgentExecutionResult(
        agent_name="ticket_router_agent",
        route_name=route_name,
        status="completed",
        confidence=0.86,
        requires_human_review=True,
        output={
            "queue_name": queue_name,
            "reason": reason,
        },
        timeline=timeline,
        tool_calls=tool_calls,
        engine_events=list(run_result.events),
        interrupt=interrupt,
        checkpoint_payload={
            "question": question,
            "output": {
                "queue_name": queue_name,
                "reason": reason,
            },
            "queue_name": queue_name,
            "review_interrupt": interrupt,
        },
        checkpoint_type="engine_adapter_state",
    )


def execute_ticket_router_graph(
    *,
    question: str,
    ticket: dict[str, Any],
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    """Run the three-node ticket router graph.

    P5.3: engine-driven internally; signature unchanged so the dispatcher
    in ``graph.py`` and the ``/api/agents/runs`` route continue to work.
    """
    initial_state = GraphState(
        tenant_id="",
        user_id="",
        request_id="",
        scratchpad={"ticket": dict(ticket or {}), "question": question},
    )
    graph = build_ticket_router_graph()
    run_result = graph.run(initial_state, max_steps=6)
    return _run_result_to_execution(
        run_result,
        question=question,
        route_name=route_name,
        base_timeline=base_timeline,
    )
