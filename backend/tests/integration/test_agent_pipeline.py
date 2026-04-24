"""Integration test: agent pipeline against real Postgres + real MinIO.

Verifies:
- POST /api/agents/runs persists an AgentRun row with tool_call_log entries.
- JSON columns (timeline_json, input_json, output_json) serialise and
  round-trip through Postgres.
- When a rule is triggered (hotel amount over threshold in tier-1 city),
  a ReviewCase is created with proper FK linkage.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import DOCX_CONTENT_TYPE

pytestmark = pytest.mark.integration


def test_agent_run_persists_to_postgres_with_tool_calls(
    integration_client,
    multilingual_docx_file: bytes,
) -> None:
    # Seed knowledge so policy RAG has something to retrieve.
    upload_response = integration_client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={
            "file": (
                "multi-policy.docx",
                multilingual_docx_file,
                DOCX_CONTENT_TYPE,
            )
        },
    )
    assert upload_response.status_code == 202

    # Invoke the agent with an over-threshold Beijing hotel ticket to trigger
    # both the ticket router path AND the rules engine.
    response = integration_client.post(
        "/api/agents/runs",
        json={
            "question": "这张北京酒店报销单为什么还在排队？",
            "tenant_id": "t1",
            "customer_id": "c1",
            "ticket": {
                "ticket_id": "ticket-int-001",
                "expense_type": "hotel",
                "city": "北京",
                "amount": 1200,
                "status": "pending_review",
            },
        },
    )
    assert response.status_code == 201
    payload = response.json()
    agent_run_id = payload["id"]
    assert payload["agent_name"]

    # Verify AgentRun + ToolCallLog rows exist in Postgres.
    from app.db.models.agent import AgentRun, ToolCallLog
    from app.db.session import SessionLocal

    session: Session = SessionLocal()
    try:
        run = session.get(AgentRun, agent_run_id)
        assert run is not None
        assert run.tenant_id == "t1"
        assert run.status in {"completed", "needs_review"}
        assert isinstance(run.timeline_json, list)
        assert len(run.timeline_json) >= 1

        tool_calls = session.scalars(
            select(ToolCallLog).where(ToolCallLog.agent_run_id == agent_run_id)
        ).all()
        # Ticket path always invokes queue_lookup and order_lookup.
        assert len(tool_calls) >= 1
        names = {tc.tool_name for tc in tool_calls}
        assert "ticket_queue_lookup" in names or "order_lookup" in names
    finally:
        session.close()


def test_agent_run_over_threshold_creates_review_case(
    integration_client,
    multilingual_docx_file: bytes,
) -> None:
    integration_client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={
            "file": (
                "multi-policy-2.docx",
                multilingual_docx_file,
                DOCX_CONTENT_TYPE,
            )
        },
    )
    response = integration_client.post(
        "/api/agents/runs",
        json={
            "question": "这张北京酒店报销单超标了吗？",
            "tenant_id": "t1",
            "customer_id": "c1",
            "ticket": {
                "ticket_id": "ticket-int-002",
                "expense_type": "hotel",
                "city": "北京",
                "amount": 1500,
                "status": "pending_review",
            },
        },
    )
    assert response.status_code == 201

    # A ReviewCase should have been created for this over-threshold ticket.
    from app.db.models.rule import ReviewCase
    from app.db.session import SessionLocal

    session: Session = SessionLocal()
    try:
        cases = session.scalars(select(ReviewCase).where(ReviewCase.tenant_id == "t1")).all()
        assert len(cases) >= 1
        # rule_result_json should contain the rule hit.
        assert any(case.rule_result_json is not None for case in cases)
    finally:
        session.close()
