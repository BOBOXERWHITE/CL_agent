"""Background-task observation log (P4.4).

Celery's built-in ``result_backend`` stores one thing — the task's final
return value or exception. That's not enough for operations:

- no tenant / user scoping (we need RLS)
- no idempotency key (same doc submitted twice kicks off two ingestions)
- no business status taxonomy (``PENDING`` / ``STARTED`` / ``SUCCESS`` /
  ``FAILURE`` / ``REVOKED`` doesn't map 1:1 to what a reviewer wants to
  see)
- ``terminate=true revoke`` doesn't persist anywhere queryable
- traces are per-task and can't be joined with ``AgentRun`` / audit_log

``task_run`` is the projection designed for a product surface:
``GET /api/tasks`` can answer "what's my tenant's pending / failed work
right now" in a single SQL query. Celery keeps the execution
machinery; we keep the truth.

Unique constraint
-----------------

``(tenant_id, task_name, idempotency_key)`` is unique — a second
submission with the same key lands on an existing row instead of
spawning a new task. Callers that don't have a natural idempotency key
(e.g. "re-run eval N") pass an empty string and accept duplicates.
Empty key + unique constraint is allowed because multiple rows can
share ``''`` only if SQLite/PG treat empty strings distinctly — so in
practice callers should compose a stable key from business id + action.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskRun(Base):
    __tablename__ = "task_run"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "task_name",
            "idempotency_key",
            name="uq_task_run_tenant_task_idem",
        ),
    )

    # ``id`` = Celery task id (also the correlation key for the result
    # backend). ``str(uuid4())`` when no celery id yet (eager inline submissions).
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Who initiated it; may be blank for system-driven tasks (cron).
    user_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # Canonical task identifier (e.g. ``knowledge.ingest_document``).
    task_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    # pending | running | succeeded | failed | canceled
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # Key used for dedupe; ``NULL`` means "no dedupe" (multiple rows with
    # a NULL key never collide on the unique constraint — this is the
    # standard SQL semantics on both SQLite and PostgreSQL).
    idempotency_key: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, nullable=True)
    # How many times this task was retried by Celery's autoretry loop.
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Cross-system correlation id from ``RequestContext``; lets us join
    # this row to the audit_log and agent_event rows that triggered it.
    trace_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    # Human-friendly one-line summary shown in the dashboard.
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )
