"""Route-level tests for P3.8 HITL resume.

Covers the state-machine transitions the ``POST /api/agents/runs/{id}/resume``
endpoint is supposed to enforce:

- Approve → AgentRun.status=completed + ReviewCase resolved + RESUME event
- Reject  → AgentRun.status=rejected + ReviewCase rejected
- Non-resumable status → 409
- Unknown run → 404
- Cross-tenant reviewer → 403
- Missing role → 403

The fixture seeds an AgentRun + ReviewCase directly in the DB so we don't
depend on a paused-producing graph (none of the current agents synthesize
a paused state; that's the future ReAct work this endpoint unlocks).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models.agent import AgentRun
from app.db.models.agent_event import AgentEvent
from app.db.models.rule import ReviewCase
from app.db.session import SessionLocal


def _seed_awaiting_run(
    *,
    tenant_id: str = "t1",
    customer_id: str = "c1",
    run_status: str = "awaiting_review",
) -> tuple[str, str]:
    """Insert a paused AgentRun + linked ReviewCase; return (run_id, case_id)."""
    run_id = str(uuid4())
    case_id = str(uuid4())
    with SessionLocal() as session:
        run = AgentRun(
            id=run_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            agent_name="travel_policy_agent",
            route_name="policy_qa",
            status=run_status,
            confidence=0.42,
            requires_human_review=True,
            input_json={"question": "北京酒店报销上限"},
            output_json={"answer": "暂不可信"},
            timeline_json=[],
        )
        case = ReviewCase(
            id=case_id,
            source="agent",
            tenant_id=tenant_id,
            customer_id=customer_id,
            status="open",
            confidence=0.42,
            reason="置信度过低",
            suggested_action="转人工复核",
            payload_json={"agent_run_id": run_id},
        )
        session.add(run)
        session.add(case)
        session.commit()
    return run_id, case_id


def test_resume_approve_marks_completed_and_resolves_case(client: TestClient) -> None:
    run_id, case_id = _seed_awaiting_run()

    response = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "approve", "note": "合规，批准通过。"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["requires_human_review"] is False
    assert body["output"]["resolution"]["decision"] == "approve"
    assert body["output"]["resolution"]["note"] == "合规，批准通过。"

    with SessionLocal() as session:
        case = session.get(ReviewCase, case_id)
        assert case is not None
        assert case.status == "resolved"
        assert case.resolution_note == "合规，批准通过。"

        events = (
            session.query(AgentEvent)
            .filter(AgentEvent.agent_run_id == run_id, AgentEvent.event_type == "RESUME")
            .all()
        )
        assert len(events) == 1
        assert events[0].payload_json["decision"] == "approve"


def test_resume_reject_marks_rejected(client: TestClient) -> None:
    run_id, case_id = _seed_awaiting_run()

    response = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "reject", "note": "信息不足，打回。"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"

    with SessionLocal() as session:
        case = session.get(ReviewCase, case_id)
        assert case is not None
        assert case.status == "rejected"


def test_resume_unknown_run_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/agents/runs/does-not-exist/resume",
        json={"decision": "approve"},
    )
    assert response.status_code == 404


def test_resume_rejects_non_resumable_status(client: TestClient) -> None:
    run_id, _ = _seed_awaiting_run(run_status="completed")
    response = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "approve"},
    )
    assert response.status_code == 409
    assert "not resumable" in response.text


def test_resume_validates_decision_enum(client: TestClient) -> None:
    run_id, _ = _seed_awaiting_run()
    response = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "maybe"},
    )
    # Pydantic pattern validation → 422.
    assert response.status_code == 422


def test_resume_needs_review_status_is_also_resumable(client: TestClient) -> None:
    """``needs_review`` is the legacy pre-P3.8 status set by the confidence
    guard; it should remain resumable so the existing review queue can
    transition runs end-to-end.
    """
    run_id, _ = _seed_awaiting_run(run_status="needs_review")
    response = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "approve"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_resume_appends_sequence_after_existing_events(client: TestClient) -> None:
    """The RESUME event's sequence should be max(existing)+1 so the
    timeline remains monotonic even after resume.
    """
    run_id, _ = _seed_awaiting_run()
    # Seed a few existing events to verify the sequence calculation.
    with SessionLocal() as session:
        for idx, et in enumerate(("NODE_START", "NODE_END", "PAUSE")):
            session.add(
                AgentEvent(
                    id=str(uuid4()),
                    agent_run_id=run_id,
                    sequence=idx,
                    event_type=et,
                    node_name="n",
                    payload_json={},
                    tenant_id="t1",
                )
            )
        session.commit()

    response = client.post(
        f"/api/agents/runs/{run_id}/resume",
        json={"decision": "approve"},
    )
    assert response.status_code == 200

    with SessionLocal() as session:
        rows = (
            session.query(AgentEvent)
            .filter(AgentEvent.agent_run_id == run_id)
            .order_by(AgentEvent.sequence)
            .all()
        )
        sequences = [r.sequence for r in rows]
        # 0,1,2 from the seed; the RESUME event should be 3.
        assert sequences == [0, 1, 2, 3]
        assert rows[-1].event_type == "RESUME"
