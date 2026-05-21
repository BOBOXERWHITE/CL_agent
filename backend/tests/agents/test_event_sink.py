"""Unit tests for the P3.7 structured event sink.

We use a throwaway SQLite schema bound to a real ``Session`` so the tests
exercise the actual ORM mapping (column defaults, FK, JSON round-trip)
rather than mocking the session. Keeps them fast — no postgres needed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.agent import AgentRun, AgentThread
from app.db.models.agent_event import AgentEvent
from app.services.agents.engine import EventType, TimelineEvent
from app.services.agents.event_sink import persist_agent_events


@pytest.fixture()
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite per test; ``create_all`` covers all models."""
    engine = create_engine("sqlite://", future=True)
    # Import every model so Base.metadata knows every table.
    from app.db.models import (  # noqa: F401
        agent,
        agent_event,
        audit_log,
        conversation,
        eval,
        knowledge,
        prompt_template,
        rag_recall_log,
        rule,
        runtime_log,
        system_setting,
    )

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _make_agent_run(session: Session, *, run_id: str = "run-1", tenant_id: str = "t1") -> AgentRun:
    session.add(
        AgentThread(
            id=run_id,
            tenant_id=tenant_id,
            customer_id="c1",
            domain="policy",
            specialist="policy_supervisor_agent",
            status="active",
        )
    )
    run = AgentRun(
        id=run_id,
        thread_id=run_id,
        tenant_id=tenant_id,
        customer_id="c1",
        agent_name="policy_supervisor_agent",
        route_name="policy_qa",
        status="completed",
        confidence=0.9,
        requires_human_review=False,
        input_json={"question": "q"},
        output_json={"answer": "a"},
        timeline_json=[],
    )
    session.add(run)
    session.flush()
    return run


def _event(
    sequence: int, event_type: EventType, node: str, payload: dict | None = None
) -> TimelineEvent:
    return TimelineEvent(
        sequence=sequence,
        event_type=event_type,
        node_name=node,
        payload=payload or {},
        timestamp=datetime.now(UTC),
    )


def test_persist_inserts_every_event_and_returns_count(session: Session) -> None:
    run = _make_agent_run(session)
    events = [
        _event(0, EventType.NODE_START, "plan"),
        _event(1, EventType.TOOL_CALL_END, "act", {"tool": "policy_search", "status": "completed"}),
        _event(2, EventType.NODE_END, "finalize", {"next_node": None}),
    ]

    count = persist_agent_events(
        session,
        agent_run_id=run.id,
        tenant_id=run.tenant_id,
        events=events,
    )
    session.commit()

    assert count == 3
    rows = list(
        session.execute(
            select(AgentEvent)
            .where(AgentEvent.agent_run_id == run.id)
            .order_by(AgentEvent.sequence)
        ).scalars()
    )
    assert [row.sequence for row in rows] == [0, 1, 2]
    assert [row.event_type for row in rows] == [
        EventType.NODE_START.value,
        EventType.TOOL_CALL_END.value,
        EventType.NODE_END.value,
    ]
    assert rows[0].node_name == "plan"
    assert rows[1].payload_json == {"tool": "policy_search", "status": "completed"}


def test_persist_scopes_rows_to_caller_tenant(session: Session) -> None:
    """``tenant_id`` on the event row is taken verbatim from the caller,
    not from the event payload — the route decides tenancy, not the graph.
    """
    run = _make_agent_run(session, tenant_id="tenant-a")
    persist_agent_events(
        session,
        agent_run_id=run.id,
        tenant_id="tenant-a",
        events=[_event(0, EventType.GRAPH_END, "")],
    )
    session.commit()

    row = session.execute(select(AgentEvent).where(AgentEvent.agent_run_id == run.id)).scalar_one()
    assert row.tenant_id == "tenant-a"


def test_persist_preserves_sequence_order(session: Session) -> None:
    run = _make_agent_run(session)
    # Pass events out of creation order; the sink should preserve what the
    # caller gave us because the ``sequence`` column is the ordering key.
    events = [
        _event(5, EventType.NODE_END, "finalize"),
        _event(0, EventType.NODE_START, "plan"),
        _event(3, EventType.TOOL_CALL_START, "act"),
    ]
    persist_agent_events(
        session,
        agent_run_id=run.id,
        tenant_id=run.tenant_id,
        events=events,
    )
    session.commit()

    sequences = [
        row.sequence
        for row in session.execute(
            select(AgentEvent)
            .where(AgentEvent.agent_run_id == run.id)
            .order_by(AgentEvent.sequence)
        ).scalars()
    ]
    assert sequences == [0, 3, 5]


def test_persist_no_events_is_noop(session: Session) -> None:
    run = _make_agent_run(session)
    count = persist_agent_events(
        session,
        agent_run_id=run.id,
        tenant_id=run.tenant_id,
        events=[],
    )
    session.commit()

    assert count == 0
    rows = session.execute(select(AgentEvent)).scalars().all()
    assert rows == []


def test_persist_accepts_iterable_generator(session: Session) -> None:
    """The signature takes ``Iterable``; a generator should work without
    the caller having to materialize a list first.
    """
    run = _make_agent_run(session)

    def _gen():
        yield _event(0, EventType.NODE_START, "plan")
        yield _event(1, EventType.NODE_END, "plan")

    count = persist_agent_events(
        session,
        agent_run_id=run.id,
        tenant_id=run.tenant_id,
        events=_gen(),
    )
    session.commit()

    assert count == 2
    assert (
        session.execute(select(AgentEvent).where(AgentEvent.agent_run_id == run.id))
        .scalars()
        .all()
        .__len__()
        == 2
    )


def test_persist_deep_copies_payload_to_guard_against_caller_mutation(session: Session) -> None:
    """If the caller reuses a payload dict, subsequent mutations must not
    leak into the persisted row. The sink wraps ``payload`` in ``dict(...)``
    so this test pins that contract.
    """
    run = _make_agent_run(session)
    payload = {"tool": "policy_search"}
    event = TimelineEvent(
        sequence=0,
        event_type=EventType.TOOL_CALL_START,
        node_name="act",
        payload=payload,
    )
    persist_agent_events(
        session,
        agent_run_id=run.id,
        tenant_id=run.tenant_id,
        events=[event],
    )
    session.commit()

    # Mutate the dict the caller still holds; the DB row should be untouched.
    payload["tool"] = "tampered"

    row = session.execute(select(AgentEvent).where(AgentEvent.agent_run_id == run.id)).scalar_one()
    assert row.payload_json == {"tool": "policy_search"}


def test_rollback_discards_inserted_events(session: Session) -> None:
    """The sink does not commit; a rollback should remove everything,
    so a failing outer transaction rolls back the event stream with it.
    """
    run = _make_agent_run(session)
    persist_agent_events(
        session,
        agent_run_id=run.id,
        tenant_id=run.tenant_id,
        events=[_event(0, EventType.NODE_START, "plan")],
    )
    # Simulate the caller aborting before commit.
    session.rollback()

    rows = session.execute(select(AgentEvent)).scalars().all()
    assert rows == []
