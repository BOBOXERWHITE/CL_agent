"""P5.3: verify ticket_router + anomaly graph now produce engine_events.

Before P5.3 both agents were single-function pipelines; their
``AgentExecutionResult.engine_events`` was always empty. After P5.3
they go through the P3.1 engine so every run yields NODE_START /
NODE_END / TOOL_CALL_END events that the ``agent_event`` table can
persist.

Parity with the pre-migration behaviour is the primary contract:
answer / queue / confidence / citations must be identical. These tests
pin both.
"""

from __future__ import annotations

from app.services.agents.anomaly_graph import execute_anomaly_graph
from app.services.agents.engine import EventType
from app.services.agents.ticket_router_graph import execute_ticket_router_graph


def test_anomaly_run_produces_engine_events() -> None:
    result = execute_anomaly_graph(
        question="这笔重复预订怎么处理？",
        route_name="order_anomaly",
        base_timeline=[],
    )
    assert result.engine_events, "anomaly agent must now emit engine events"
    event_types = {event.event_type for event in result.engine_events}
    # Every run goes classify → route → GRAPH_END, so both NODE_START
    # and NODE_END must appear at minimum.
    assert EventType.NODE_START in event_types
    assert EventType.NODE_END in event_types
    assert EventType.GRAPH_END in event_types


def test_anomaly_output_shape_unchanged_after_migration() -> None:
    """Parity pin: the legacy output fields (code / queue_name / reason /
    matched_signals) must stay identical to P3.4 semantics.
    """
    result = execute_anomaly_graph(
        question="这笔重复预订怎么处理？",
        route_name="order_anomaly",
        base_timeline=[],
    )
    assert result.output["code"] == "duplicate_booking"
    assert result.output["queue_name"] == "ops-review"
    assert "重复预订" in result.output["matched_signals"]
    assert result.agent_name == "order_anomaly_agent"
    assert result.requires_human_review is True


def test_anomaly_no_match_still_produces_events() -> None:
    """Fallback path (no keyword hit) must still emit NODE_START /
    NODE_END — the event stream is an unconditional observation.
    """
    result = execute_anomaly_graph(
        question="完全不相关的问题 xyzzy",
        route_name="order_anomaly",
        base_timeline=[],
    )
    assert result.output["code"] == "unknown"
    assert result.confidence == 0.35
    assert result.engine_events  # still populated


def test_ticket_router_run_produces_engine_events() -> None:
    ticket = {
        "ticket_id": "T-1001",
        "expense_type": "hotel",
        "city": "上海",
        "amount": 1200,
        "status": "pending_review",
    }
    result = execute_ticket_router_graph(
        question="这张工单应该分到哪个组？",
        ticket=ticket,
        route_name="ticket_triage",
        base_timeline=[],
    )
    assert result.engine_events
    event_types = [event.event_type for event in result.engine_events]
    # We expect exactly three NODE_START rows (queue_lookup, order_lookup,
    # finalize) — guards against accidentally regressing to a
    # single-function pipeline.
    start_count = sum(1 for et in event_types if et == EventType.NODE_START)
    assert start_count == 3


def test_ticket_router_tool_calls_preserved() -> None:
    """The two tool calls (queue_lookup + order_lookup) must still land
    on ``tool_calls`` so the review UI keeps rendering them.
    """
    ticket = {
        "ticket_id": "T-2002",
        "expense_type": "meal",
        "city": "北京",
        "amount": 120,
        "status": "pending_review",
    }
    result = execute_ticket_router_graph(
        question="这个餐费工单",
        ticket=ticket,
        route_name="ticket_triage",
        base_timeline=[],
    )
    tool_names = [tc.tool_name for tc in result.tool_calls]
    assert tool_names == ["ticket_queue_lookup", "order_lookup"]
    assert result.agent_name == "ticket_router_agent"
    assert result.confidence == 0.86


def test_anomaly_timeline_still_has_human_checkpoint() -> None:
    """Legacy timeline contract: the final step is a human review
    checkpoint. Dashboards and review queue UI depend on this.
    """
    result = execute_anomaly_graph(
        question="退款争议",
        route_name="order_anomaly",
        base_timeline=[],
    )
    checkpoint_steps = [s for s in result.timeline if s.node_name == "human_review_checkpoint"]
    assert len(checkpoint_steps) == 1
    assert checkpoint_steps[0].status == "required"


def test_ticket_router_timeline_still_has_all_four_steps() -> None:
    ticket = {
        "ticket_id": "T-3003",
        "expense_type": "flight",
        "city": "上海",
        "amount": 3000,
        "status": "pending_review",
    }
    result = execute_ticket_router_graph(
        question="机票工单",
        ticket=ticket,
        route_name="ticket_triage",
        base_timeline=[],
    )
    node_names = [step.node_name for step in result.timeline]
    assert node_names == [
        "ticket_triage",
        "ticket_queue_lookup",
        "order_lookup",
        "human_review_checkpoint",
    ]
