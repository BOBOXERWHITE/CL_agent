from __future__ import annotations

from app.db.models.agent import AgentRun, AgentThread, AgentThreadCheckpoint
from app.db.session import SessionLocal


def test_ticket_run_persists_thread_checkpoint_and_interrupt(client) -> None:
    response = client.post(
        "/api/agents/runs",
        json={
            "question": "这张北京酒店报销单为什么还在排队？",
            "tenant_id": "t1",
            "customer_id": "c1",
            "ticket": {
                "ticket_id": "ticket-phase10-001",
                "expense_type": "hotel",
                "city": "北京",
                "amount": 1200,
                "status": "pending_review",
            },
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["thread_status"] == "awaiting_review"
    assert body["pending_interrupt"]["queue_name"] == "finance-review"
    assert body["latest_checkpoint"]["checkpoint_type"] == "engine_adapter_state"
    assert body["latest_checkpoint"]["status"] == "paused"
    assert body["output"]["orchestration_trace"]["agent_name"] == "ticket_router_agent"
    assert body["output"]["orchestration_trace"]["route_name"] == "ticket_triage"
    assert body["output"]["orchestration_trace"]["queue_name"] == "finance-review"
    assert (
        body["output"]["orchestration_trace"]["pending_interrupt"]["queue_name"] == "finance-review"
    )
    assert (
        body["output"]["orchestration_trace"]["latest_checkpoint"]["checkpoint_type"]
        == "engine_adapter_state"
    )
    assert body["output"]["orchestration_trace"]["timeline_nodes"][0]["node_name"] == "router"
    assert (
        body["output"]["orchestration_trace"]["tool_calls"][0]["tool_name"] == "ticket_queue_lookup"
    )
    trace_events = body["output"]["orchestration_trace"]["trace_events"]
    assert any(
        event["category"] == "interrupt"
        and event["name"] == "human_review"
        and event["detail"] == "ticket routing requires operator review"
        for event in trace_events
    )
    assert any(
        event["category"] == "checkpoint"
        and event["name"] == "checkpoint_state"
        and event["detail"] == "engine_adapter_state"
        for event in trace_events
    )

    with SessionLocal() as session:
        agent_run = session.get(AgentRun, body["id"])
        assert agent_run is not None
        thread = session.get(AgentThread, body["thread_id"])
        assert thread is not None
        assert thread.domain == "ticket"
        assert thread.specialist == "ticket_router_agent"
        assert thread.status == "awaiting_review"
        assert thread.latest_checkpoint_id
        assert thread.pending_interrupt_json["kind"] == "human_review"
        assert thread.pending_interrupt_json["queue_name"] == "finance-review"
        assert thread.pending_interrupt_json["allowed_decisions"] == [
            "approve",
            "edit",
            "reject",
        ]

        checkpoint = session.get(AgentThreadCheckpoint, thread.latest_checkpoint_id)
        assert checkpoint is not None
        assert checkpoint.agent_run_id == agent_run.id
        assert checkpoint.checkpoint_type == "engine_adapter_state"
        assert checkpoint.status == "paused"
        assert checkpoint.pending_interrupt_json["queue_name"] == "finance-review"
        assert checkpoint.state_json["agent_name"] == "ticket_router_agent"
        assert checkpoint.state_json["route_name"] == "ticket_triage"
        assert checkpoint.state_json["output"]["queue_name"] == "finance-review"


def test_anomaly_run_persists_thread_checkpoint_and_interrupt(client) -> None:
    response = client.post(
        "/api/agents/runs",
        json={
            "question": "这是重复预订的异常订单，需要人工排查",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["thread_status"] == "awaiting_review"
    assert body["pending_interrupt"]["anomaly_code"] == "duplicate_booking"
    assert body["latest_checkpoint"]["checkpoint_type"] == "engine_adapter_state"
    assert body["latest_checkpoint"]["status"] == "paused"
    assert body["output"]["orchestration_trace"]["agent_name"] == "order_anomaly_agent"
    assert body["output"]["orchestration_trace"]["route_name"] == "order_anomaly"
    assert (
        body["output"]["orchestration_trace"]["pending_interrupt"]["anomaly_code"]
        == "duplicate_booking"
    )
    assert (
        body["output"]["orchestration_trace"]["latest_checkpoint"]["checkpoint_type"]
        == "engine_adapter_state"
    )
    assert body["output"]["orchestration_trace"]["timeline_nodes"][0]["node_name"] == "router"
    trace_events = body["output"]["orchestration_trace"]["trace_events"]
    assert any(
        event["category"] == "interrupt"
        and event["name"] == "human_review"
        and event["metadata"]["anomaly_code"] == "duplicate_booking"
        for event in trace_events
    )
    assert any(
        event["category"] == "checkpoint"
        and event["name"] == "checkpoint_state"
        and event["detail"] == "engine_adapter_state"
        for event in trace_events
    )

    with SessionLocal() as session:
        agent_run = session.get(AgentRun, body["id"])
        assert agent_run is not None
        thread = session.get(AgentThread, body["thread_id"])
        assert thread is not None
        assert thread.domain == "anomaly"
        assert thread.specialist == "order_anomaly_agent"
        assert thread.status == "awaiting_review"
        assert thread.latest_checkpoint_id
        assert thread.pending_interrupt_json["kind"] == "human_review"
        assert thread.pending_interrupt_json["queue_name"] == "ops-review"
        assert thread.pending_interrupt_json["anomaly_code"] == "duplicate_booking"
        assert thread.pending_interrupt_json["allowed_decisions"] == [
            "approve",
            "edit",
            "reject",
        ]

        checkpoint = session.get(AgentThreadCheckpoint, thread.latest_checkpoint_id)
        assert checkpoint is not None
        assert checkpoint.agent_run_id == agent_run.id
        assert checkpoint.checkpoint_type == "engine_adapter_state"
        assert checkpoint.status == "paused"
        assert checkpoint.pending_interrupt_json["anomaly_code"] == "duplicate_booking"
        assert checkpoint.state_json["agent_name"] == "order_anomaly_agent"
        assert checkpoint.state_json["route_name"] == "order_anomaly"
        assert checkpoint.state_json["output"]["code"] == "duplicate_booking"
