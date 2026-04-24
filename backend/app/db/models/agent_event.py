"""Structured agent event log (P3.7).

Until now, ``AgentRun.timeline_json`` was a free-form JSON blob with
``status`` as an arbitrary string and ``detail`` as free text. Useful
for a human reading one row, hostile to every other operation:

- you cannot ``SELECT * FROM agent_event WHERE event_type='TOOL_CALL_END'``
  because the blob is opaque to SQL;
- you cannot build a dashboard of "percentage of agent runs that hit
  max_steps" without parsing JSON in every query;
- timeline order depends on insertion order inside the JSON array, not
  a real sequence column.

This table is the structured source of truth: one row per engine
``TimelineEvent``, indexed by ``agent_run_id`` + ``sequence`` so an
ordered replay is a single SELECT. ``AgentRun.timeline_json`` stays as
a cached display view -- P3.3's legacy adapter still writes it so the
existing API / frontend work unchanged.

Event vocabulary matches ``agents.engine.EventType``; we keep it as a
text column (not a DB enum) so adding new event kinds doesn't need a
migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentEvent(Base):
    __tablename__ = "agent_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_run.id", ondelete="CASCADE"),
        index=True,
    )
    # Sequence is assigned by the engine; unique per run starting at 0.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    node_name: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Same tenant_id as the parent AgentRun so RLS scopes this table too.
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
