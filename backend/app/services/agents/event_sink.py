"""Persistence of structured agent events to the ``agent_event`` table (P3.7).

Callers in the agents package produce ``TimelineEvent`` objects via the
engine. The route handler (``/api/agents/runs``) is where we decide
*when* to flush them -- right after the ``AgentRun`` row is inserted,
in the same transaction, so a rolled-back run also rolls back its
event stream.

We keep this in its own module so that graph code stays free of DB
dependencies. The graph returns events, the route flushes them.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models.agent_event import AgentEvent
from app.services.agents.engine import TimelineEvent


def persist_agent_events(
    session: Session,
    *,
    agent_run_id: str,
    tenant_id: str,
    events: Iterable[TimelineEvent],
) -> int:
    """Insert every event into ``agent_event``; return the count.

    The caller owns commit/rollback. Events are expected to come in
    sequence order already (the engine guarantees that), so we just
    pass them through.

    P5-patch-A: records the write as a business span so trace backends
    can show "this agent run produced N events in X ms" next to the
    chat / policy_qa spans.
    """
    from app.core.observability.tracing import trace_span

    count = 0
    with trace_span(
        "agent_event.persist",
        agent_run_id=agent_run_id,
        tenant_id=tenant_id,
    ) as span:
        for event in events:
            session.add(
                AgentEvent(
                    id=str(uuid4()),
                    agent_run_id=agent_run_id,
                    sequence=event.sequence,
                    event_type=event.event_type.value,
                    node_name=event.node_name,
                    payload_json=dict(event.payload),
                    tenant_id=tenant_id,
                )
            )
            count += 1
        span.set_attr("event_count", count)
    return count


__all__ = ["persist_agent_events"]
