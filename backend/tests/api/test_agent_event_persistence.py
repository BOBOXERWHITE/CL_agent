"""Route-level test for P3.7: ``/api/agents/runs`` must flush the
structured engine events to the ``agent_event`` table in the same
transaction as the ``AgentRun`` row.

We don't assert on exact event wording (those are engine-internal) -- just
that a policy-QA run produces at least one ``NODE_START`` row scoped to
the same agent_run_id and tenant_id the API returned.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.models.agent_event import AgentEvent
from app.db.session import SessionLocal


def test_policy_qa_run_persists_engine_events(client: TestClient) -> None:
    response = client.post(
        "/api/agents/runs",
        json={
            "question": "请问差旅政策中经济舱改签规则怎么写？",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]

    with SessionLocal() as session:
        rows = (
            session.query(AgentEvent)
            .filter(AgentEvent.agent_run_id == run_id)
            .order_by(AgentEvent.sequence)
            .all()
        )

    assert rows, "policy-QA run should have produced structured engine events"
    # Every row belongs to the same tenant as the request.
    assert {row.tenant_id for row in rows} == {"t1"}
    # The first event is always NODE_START emitted by the engine.
    assert rows[0].event_type == "NODE_START"
    # Sequence numbers should be strictly monotonic and dense-ish starting
    # from 0 (the engine assigns them in order).
    sequences = [row.sequence for row in rows]
    assert sequences[0] == 0
    assert sequences == sorted(sequences)


def test_ticket_router_run_now_produces_engine_events(
    client: TestClient,
) -> None:
    """P5.3: ticket_router migrated to the engine — its runs now
    produce structured events too. We still want to verify the route
    doesn't crash and that events land on ``agent_event`` scoped to
    the right run.
    """
    response = client.post(
        "/api/agents/runs",
        json={
            "question": "这张工单怎么走？",
            "tenant_id": "t1",
            "customer_id": "c1",
            "ticket": {
                "ticket_id": "ticket-42",
                "expense_type": "meal",
                "city": "上海",
                "amount": 120,
                "status": "pending_review",
            },
        },
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]

    with SessionLocal() as session:
        rows = session.query(AgentEvent).filter(AgentEvent.agent_run_id == run_id).all()
    # Three engine nodes (queue_lookup, order_lookup, finalize) + their
    # NODE_END events + GRAPH_END → strictly more than zero.
    assert rows, "ticket_router should now emit engine events (P5.3)"
    event_types = {row.event_type for row in rows}
    assert "NODE_START" in event_types
    assert "NODE_END" in event_types


def test_anomaly_run_produces_engine_events(client: TestClient) -> None:
    """P5.3: anomaly_graph also migrated to the engine."""
    response = client.post(
        "/api/agents/runs",
        json={
            "question": "疑似重复预订，帮我查一下",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]

    with SessionLocal() as session:
        rows = session.query(AgentEvent).filter(AgentEvent.agent_run_id == run_id).all()
    assert rows, "anomaly agent should now emit engine events (P5.3)"
    assert {row.tenant_id for row in rows} == {"t1"}
