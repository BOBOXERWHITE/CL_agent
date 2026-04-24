"""P5.4: ``ReviewCase.agent_run_id`` FK column tests.

Verifies three behaviours:

1. The route's ``create_review_case`` call populates the FK column
   (not just ``payload_json``).
2. HITL resume finds the linked ReviewCase via the FK column in a
   single SQL query.
3. The ``payload_json.agent_run_id`` fallback still works for rows
   that predate the migration (deprecation window).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models.agent import AgentRun
from app.db.models.rule import ReviewCase
from app.db.session import SessionLocal


def test_review_case_populates_agent_run_id_column(client: TestClient) -> None:
    """Trigger the rule-blocked path (hotel + Beijing + over-cap amount)
    which creates a ReviewCase. The new FK column must be set."""
    resp = client.post(
        "/api/agents/runs",
        json={
            "question": "这张北京酒店报销单为什么被拦截？",
            "tenant_id": "t1",
            "customer_id": "c1",
            "ticket": {
                "ticket_id": "ticket-fk-1",
                "expense_type": "hotel",
                "city": "北京",
                "amount": 2500,
                "status": "pending_review",
            },
        },
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    with SessionLocal() as session:
        cases = session.query(ReviewCase).filter(ReviewCase.agent_run_id == run_id).all()
    assert len(cases) == 1
    assert cases[0].agent_run_id == run_id
    # Old payload_json link still populated (deprecation window).
    assert (cases[0].payload_json or {}).get("agent_run_id") == run_id


def test_resume_finds_linked_case_via_fk_column(client: TestClient) -> None:
    """Seed an AgentRun + a ReviewCase linked by FK only (not by
    payload_json) and verify resume still resolves it.
    """
    run_id = str(uuid4())
    case_id = str(uuid4())
    with SessionLocal() as session:
        session.add(
            AgentRun(
                id=run_id,
                tenant_id="t1",
                customer_id="c1",
                agent_name="travel_policy_agent",
                route_name="policy_qa",
                status="awaiting_review",
                confidence=0.5,
                requires_human_review=True,
                input_json={"question": "q"},
                output_json={},
                timeline_json=[],
            )
        )
        session.add(
            ReviewCase(
                id=case_id,
                source="agent",
                tenant_id="t1",
                customer_id="c1",
                status="open",
                confidence=0.5,
                reason="test",
                suggested_action="转人工复核",
                payload_json={},  # NO agent_run_id here — only FK column
                agent_run_id=run_id,
            )
        )
        session.commit()

    resp = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "approve", "note": "ok"},
    )
    assert resp.status_code == 200
    with SessionLocal() as session:
        case = session.get(ReviewCase, case_id)
        assert case is not None
        assert case.status == "resolved"


def test_resume_falls_back_to_payload_json_for_legacy_rows(client: TestClient) -> None:
    """Legacy rows without ``agent_run_id`` FK column but with
    ``payload_json.agent_run_id`` must still resolve — deprecation
    window compatibility.
    """
    run_id = str(uuid4())
    case_id = str(uuid4())
    with SessionLocal() as session:
        session.add(
            AgentRun(
                id=run_id,
                tenant_id="t1",
                customer_id="c1",
                agent_name="travel_policy_agent",
                route_name="policy_qa",
                status="awaiting_review",
                confidence=0.5,
                requires_human_review=True,
                input_json={},
                output_json={},
                timeline_json=[],
            )
        )
        session.add(
            ReviewCase(
                id=case_id,
                source="agent",
                tenant_id="t1",
                customer_id="c1",
                status="open",
                confidence=0.5,
                reason="legacy",
                suggested_action="转人工复核",
                payload_json={"agent_run_id": run_id},  # old style
                agent_run_id=None,  # NOT yet backfilled
            )
        )
        session.commit()

    resp = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "approve", "note": "backcompat"},
    )
    assert resp.status_code == 200

    with SessionLocal() as session:
        case = session.get(ReviewCase, case_id)
        assert case is not None
        assert case.status == "resolved"


def test_create_review_case_lifts_agent_run_id_from_payload(client: TestClient) -> None:
    """Call sites that still only pass ``agent_run_id`` via ``payload``
    shouldn't break — ``create_review_case`` lifts it up into the
    explicit column for them.

    ``client`` fixture is unused here, but we depend on it solely so
    the FastAPI lifespan (schema bootstrap) runs before we poke the DB
    directly.
    """
    from app.services.rules.engine import create_review_case

    assert client is not None  # make the fixture dependency explicit
    with SessionLocal() as session:
        case = create_review_case(
            session,
            source="agent",
            tenant_id="t1",
            customer_id="c1",
            confidence=0.5,
            reason="lift-test",
            payload={"agent_run_id": "legacy-run-123"},
        )
    assert case.agent_run_id == "legacy-run-123"
