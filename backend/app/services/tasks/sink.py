"""Write-side helpers for the ``task_run`` table (P4.4).

Every Celery task hand-off crosses one of the following boundaries:

- **Route → submission**: the web process calls ``register_task`` before
  handing anything off. If the (tenant, task_name, idempotency_key)
  tuple already has a succeeded row we **return that row's id** instead
  of launching a new task — the dedupe happens here, not inside Celery.
- **Worker start**: ``mark_running`` flips ``pending → running`` and
  stamps the retry counter (so the dashboard can tell "first try" vs
  "3rd retry").
- **Worker finish (ok)**: ``mark_succeeded`` stores the result + sets
  ``finished_at``.
- **Worker finish (error)**: ``mark_failed`` stores the exception +
  sets ``finished_at``.
- **Reviewer cancels**: ``mark_canceled`` is called from the route
  (see P4.5) after Celery's ``revoke``.

All functions take an explicit ``Session`` so the caller owns
commit/rollback. Celery tasks compose their own short-lived
``bypass_rls_session`` (workers have no per-request tenant context).

Why a dedicated module
----------------------

Keeping this out of ``app/workers/tasks.py`` means the Celery decorator
chain is a thin wrapper around the pipeline function; the sink can be
unit-tested with a plain ``Session`` + no broker. It also lets the
API routes call ``register_task`` without importing ``celery_app``
(which transitively needs a broker URL).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.task_run import TaskRun

_log = logging.getLogger(__name__)


# Canonical status vocabulary. Kept as strings (not an enum) so future
# status kinds don't require a migration — follows the same precedent
# as AgentEvent.event_type.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"

TERMINAL_STATUSES = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELED})


class TaskAlreadyExists(Exception):
    """Raised by callers that want to detect duplicate submissions.

    ``register_task`` does NOT raise this by itself — it returns the
    existing row so the caller can short-circuit. Callers that prefer
    an exception-driven control flow can raise it explicitly.
    """

    def __init__(self, task_run: TaskRun) -> None:
        super().__init__(f"task_run already exists: id={task_run.id} status={task_run.status}")
        self.task_run = task_run


def find_existing(
    session: Session,
    *,
    tenant_id: str,
    task_name: str,
    idempotency_key: str | None,
) -> TaskRun | None:
    """Return the existing task_run matching the idempotency tuple, or None.

    Empty / ``None`` ``idempotency_key`` means "no dedupe" — always
    returns None so the caller creates a fresh row.
    """
    if not idempotency_key:
        return None
    return session.execute(
        select(TaskRun).where(
            TaskRun.tenant_id == tenant_id,
            TaskRun.task_name == task_name,
            TaskRun.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def register_task(
    session: Session,
    *,
    task_id: str,
    tenant_id: str,
    task_name: str,
    user_id: str = "",
    idempotency_key: str | None = None,
    input_payload: dict[str, Any] | None = None,
    trace_id: str = "",
    summary: str = "",
) -> TaskRun:
    """Insert a ``pending`` task_run, or return an existing row when the
    idempotency tuple already has one.

    The caller commits; we do a ``flush()`` so the row is visible to
    subsequent ``SELECT``s within the same transaction.
    """
    # Normalise empty-string keys to ``None`` so the unique constraint
    # doesn't treat every "opt-out" submission as colliding with every
    # other opt-out submission.
    normalised_key = idempotency_key or None
    if normalised_key:
        existing = find_existing(
            session,
            tenant_id=tenant_id,
            task_name=task_name,
            idempotency_key=normalised_key,
        )
        if existing is not None:
            _log.info(
                "task_run_deduped",
                extra={
                    "task_id": existing.id,
                    "task_name": task_name,
                    "idempotency_key": normalised_key,
                    "existing_status": existing.status,
                },
            )
            return existing

    row = TaskRun(
        id=task_id,
        tenant_id=tenant_id,
        user_id=user_id,
        task_name=task_name,
        status=STATUS_PENDING,
        idempotency_key=normalised_key,
        input_json=dict(input_payload or {}),
        trace_id=trace_id,
        summary=summary,
    )
    session.add(row)
    session.flush()
    return row


def mark_running(session: Session, *, task_id: str, retries: int = 0) -> TaskRun | None:
    """Promote ``pending → running``. No-op if the row is already terminal."""
    row = session.get(TaskRun, task_id)
    if row is None:
        return None
    if row.status in TERMINAL_STATUSES:
        return row
    row.status = STATUS_RUNNING
    row.retries = max(row.retries, retries)
    session.add(row)
    session.flush()
    return row


def mark_succeeded(
    session: Session,
    *,
    task_id: str,
    result: dict[str, Any] | None = None,
) -> TaskRun | None:
    row = session.get(TaskRun, task_id)
    if row is None:
        return None
    row.status = STATUS_SUCCEEDED
    row.result_json = dict(result or {})
    row.error_json = None
    row.finished_at = datetime.now(UTC)
    session.add(row)
    session.flush()
    return row


def mark_failed(
    session: Session,
    *,
    task_id: str,
    error: dict[str, Any] | None = None,
    retries: int = 0,
) -> TaskRun | None:
    row = session.get(TaskRun, task_id)
    if row is None:
        return None
    row.status = STATUS_FAILED
    row.error_json = dict(error or {})
    row.retries = max(row.retries, retries)
    row.finished_at = datetime.now(UTC)
    session.add(row)
    session.flush()
    return row


def mark_canceled(session: Session, *, task_id: str, note: str = "") -> TaskRun | None:
    """Record a reviewer-initiated cancellation. Idempotent: re-canceling
    a canceled row is a no-op so the route can retry safely.
    """
    row = session.get(TaskRun, task_id)
    if row is None:
        return None
    if row.status == STATUS_CANCELED:
        return row
    row.status = STATUS_CANCELED
    row.error_json = {"reason": "canceled_by_reviewer", "note": note}
    row.finished_at = datetime.now(UTC)
    session.add(row)
    session.flush()
    return row


__all__ = [
    "STATUS_CANCELED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_SUCCEEDED",
    "TERMINAL_STATUSES",
    "TaskAlreadyExists",
    "find_existing",
    "mark_canceled",
    "mark_failed",
    "mark_running",
    "mark_succeeded",
    "register_task",
]
