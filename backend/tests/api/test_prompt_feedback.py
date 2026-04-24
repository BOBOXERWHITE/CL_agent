"""P6.3 / P6.4: feedback + stats + transition endpoint tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models.conversation import ChatMessage, ChatSession
from app.db.models.prompt_feedback import PromptFeedback
from app.db.models.prompt_selection_log import PromptSelectionLog
from app.db.models.prompt_template import PromptTemplate
from app.db.session import SessionLocal


def _create_template(client: TestClient, name: str = "v1") -> str:
    resp = client.post(
        "/api/prompts",
        json={"name": name, "task_type": "policy_answer", "template": "body"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_chat_with_answer(
    *,
    tenant_id: str = "default-tenant",
    prompt_template_id: str | None = None,
    version: int = 1,
) -> str:
    session_id = str(uuid4())
    with SessionLocal() as session:
        session.add(ChatSession(id=session_id, tenant_id=tenant_id, customer_id="c1"))
        session.add(
            ChatMessage(
                id=str(uuid4()),
                session_id=session_id,
                role="user",
                content="q",
                metadata_json={},
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            ChatMessage(
                id=str(uuid4()),
                session_id=session_id,
                role="assistant",
                content="a",
                metadata_json={
                    "retrieval_trace": {
                        "prompt_template_id": prompt_template_id,
                        "prompt_version": version,
                    },
                },
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    return session_id


# ---------------------------------------------------------------------------
# Feedback endpoint
# ---------------------------------------------------------------------------


def test_post_feedback_attributes_to_latest_assistant_prompt(client: TestClient) -> None:
    template_id = _create_template(client)
    session_id = _seed_chat_with_answer(prompt_template_id=template_id, version=1)

    resp = client.post(
        f"/api/chat/sessions/{session_id}/feedback",
        json={"rating": "up", "comment": "nice"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["prompt_template_id"] == template_id
    assert body["version"] == 1
    assert body["rating"] == "up"

    with SessionLocal() as session:
        rows = session.query(PromptFeedback).all()
    assert len(rows) == 1
    assert rows[0].comment == "nice"
    assert rows[0].prompt_template_id == template_id


def test_post_feedback_rejects_unknown_session(client: TestClient) -> None:
    resp = client.post(
        "/api/chat/sessions/does-not-exist/feedback",
        json={"rating": "down"},
    )
    assert resp.status_code == 404


def test_post_feedback_rating_validation_enforced(client: TestClient) -> None:
    session_id = _seed_chat_with_answer()
    resp = client.post(
        f"/api/chat/sessions/{session_id}/feedback",
        json={"rating": "maybe"},
    )
    # Pydantic pattern validation → 422
    assert resp.status_code == 422


def test_post_feedback_down_rating_persisted(client: TestClient) -> None:
    template_id = _create_template(client)
    session_id = _seed_chat_with_answer(prompt_template_id=template_id)
    resp = client.post(
        f"/api/chat/sessions/{session_id}/feedback",
        json={"rating": "down", "comment": "不够准确"},
    )
    assert resp.status_code == 201
    assert resp.json()["rating"] == "down"


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


def test_stats_aggregates_up_down_counts(client: TestClient) -> None:
    template_id = _create_template(client)
    # Seed 3 up + 1 down directly (avoids needing 4 separate chat sessions).
    with SessionLocal() as session:
        for rating in ("up", "up", "up", "down"):
            session.add(
                PromptFeedback(
                    session_id=str(uuid4()),
                    tenant_id="default-tenant",
                    prompt_template_id=template_id,
                    version=1,
                    rating=rating,
                    comment="",
                    user_id="",
                )
            )
        # Also seed a few selection_log rows.
        for _ in range(5):
            session.add(
                PromptSelectionLog(
                    request_id=str(uuid4()),
                    tenant_id="default-tenant",
                    task_type="policy_answer",
                    prompt_template_id=template_id,
                    version=1,
                    variant_group="candidate",
                    selected_reason="traffic_routed",
                )
            )
        session.commit()

    resp = client.get(f"/api/prompts/{template_id}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requests"] == 5
    assert body["up_count"] == 3
    assert body["down_count"] == 1
    assert body["up_rate"] == 0.75  # 3 / 4


def test_stats_up_rate_null_when_no_feedback(client: TestClient) -> None:
    template_id = _create_template(client)
    resp = client.get(f"/api/prompts/{template_id}/stats")
    body = resp.json()
    assert body["up_count"] == 0
    assert body["down_count"] == 0
    assert body["up_rate"] is None


def test_stats_unknown_template_404(client: TestClient) -> None:
    resp = client.get("/api/prompts/does-not-exist/stats")
    assert resp.status_code == 404


def test_stats_real_avg_latency_and_confidence(client: TestClient) -> None:
    """P7.3: with latency_ms / confidence columns seeded on
    rag_recall_log rows, stats should return real averages (not null).
    """
    from app.db.models.rag_recall_log import RagRecallLog

    template_id = _create_template(client)

    with SessionLocal() as session:
        for latency, conf in ((100, 0.80), (300, 0.60), (200, 0.70)):
            session.add(
                RagRecallLog(
                    id=str(uuid4()),
                    request_id=str(uuid4()),
                    session_id=None,
                    tenant_id="default-tenant",
                    customer_id="c1",
                    question="q",
                    retrieval_mode="hybrid",
                    prompt_template_id=template_id,
                    prompt_name="n",
                    prompt_version=1,
                    model_name="m",
                    citation_count=1,
                    token_usage_json={},
                    trace_json={},
                    latency_ms=latency,
                    confidence=conf,
                )
            )
        session.commit()

    resp = client.get(f"/api/prompts/{template_id}/stats")
    body = resp.json()
    # Avg of (100, 300, 200) = 200; avg of (0.8, 0.6, 0.7) = 0.7.
    assert body["avg_latency_ms"] == 200
    assert round(body["avg_confidence"], 2) == 0.70


def test_stats_null_when_no_rag_recall_rows(client: TestClient) -> None:
    """No recall logs for this prompt → avg_latency / avg_confidence
    must stay null (not 0 — lets UI tell "no data" from "0 latency")."""
    template_id = _create_template(client)
    resp = client.get(f"/api/prompts/{template_id}/stats")
    body = resp.json()
    assert body["avg_latency_ms"] is None
    assert body["avg_confidence"] is None


def test_stats_reviewer_forbidden(client: TestClient) -> None:
    template_id = _create_template(client)
    resp = client.get(
        f"/api/prompts/{template_id}/stats",
        headers={"Authorization": "Bearer reviewer-token"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Transition endpoint (P6.1 state machine)
# ---------------------------------------------------------------------------


def test_transition_draft_to_candidate_with_traffic(client: TestClient) -> None:
    template_id = _create_template(client)
    resp = client.post(
        f"/api/prompts/{template_id}/transition",
        json={"target_status": "candidate", "traffic_percent": 25},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "candidate"
    assert body["traffic_percent"] == 25


def test_transition_candidate_to_active_archives_old(client: TestClient) -> None:
    """Promoting a candidate to active should archive the previous
    active for the same task_type."""
    old_id = _create_template(client, "old")
    new_id = _create_template(client, "new")
    client.post(
        f"/api/prompts/{old_id}/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )
    client.post(
        f"/api/prompts/{new_id}/transition",
        json={"target_status": "candidate", "traffic_percent": 50},
    )
    resp = client.post(
        f"/api/prompts/{new_id}/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )
    assert resp.status_code == 200

    with SessionLocal() as session:
        old_row = session.get(PromptTemplate, old_id)
        new_row = session.get(PromptTemplate, new_id)
        assert old_row.status == "archived"
        assert new_row.status == "active"


def test_transition_illegal_rejected_with_409(client: TestClient) -> None:
    """Archived → active must go via draft first — direct transition
    should 409 from the state-machine guard."""
    template_id = _create_template(client)
    client.post(
        f"/api/prompts/{template_id}/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )
    client.post(
        f"/api/prompts/{template_id}/transition",
        json={"target_status": "archived", "traffic_percent": 0},
    )
    resp = client.post(
        f"/api/prompts/{template_id}/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )
    assert resp.status_code == 409


def test_transition_unknown_template_404(client: TestClient) -> None:
    resp = client.post(
        "/api/prompts/missing/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )
    assert resp.status_code == 404


def test_transition_requires_admin(client: TestClient) -> None:
    template_id = _create_template(client)
    resp = client.post(
        f"/api/prompts/{template_id}/transition",
        headers={"Authorization": "Bearer operator-token"},
        json={"target_status": "active", "traffic_percent": 0},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# P6.4: promote / rollback syntactic sugar
# ---------------------------------------------------------------------------


def test_promote_candidate_to_active(client: TestClient) -> None:
    old_id = _create_template(client, "old")
    new_id = _create_template(client, "new")
    client.post(
        f"/api/prompts/{old_id}/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )
    client.post(
        f"/api/prompts/{new_id}/transition",
        json={"target_status": "candidate", "traffic_percent": 50},
    )

    resp = client.post(f"/api/prompts/{new_id}/promote", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    with SessionLocal() as session:
        old_row = session.get(PromptTemplate, old_id)
        assert old_row.status == "archived"


def test_rollback_active_to_archived(client: TestClient) -> None:
    template_id = _create_template(client)
    client.post(
        f"/api/prompts/{template_id}/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )

    resp = client.post(f"/api/prompts/{template_id}/rollback", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


def test_promote_draft_directly_to_active_is_allowed(client: TestClient) -> None:
    """Draft → active is in the allowed map (for quick-and-dirty flows
    where no A/B is needed). The promote endpoint should accept it."""
    template_id = _create_template(client)
    resp = client.post(f"/api/prompts/{template_id}/promote", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_rollback_already_archived_is_idempotent(client: TestClient) -> None:
    """Calling rollback on an already-archived row must not 5xx — it's
    the same target state; the state machine treats it as no-op."""
    template_id = _create_template(client)
    client.post(
        f"/api/prompts/{template_id}/transition",
        json={"target_status": "active", "traffic_percent": 0},
    )
    client.post(f"/api/prompts/{template_id}/rollback", json={})

    # Second rollback.
    resp = client.post(f"/api/prompts/{template_id}/rollback", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


def test_promote_requires_admin(client: TestClient) -> None:
    template_id = _create_template(client)
    resp = client.post(
        f"/api/prompts/{template_id}/promote",
        headers={"Authorization": "Bearer operator-token"},
        json={},
    )
    assert resp.status_code == 403
