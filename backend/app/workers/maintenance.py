"""Periodic housekeeping tasks (P5.5).

Currently wired: ``cleanup_old_task_runs_task``. Deletes terminal
``task_run`` rows older than ``TASK_RUN_RETENTION_DAYS`` (default 90).

Running mechanics
-----------------

- In production: ``celery -A app.workers.celery_app beat`` schedules the
  task; a separate worker process picks it up. The ``beat_schedule`` is
  configured in ``celery_app.py`` (P5.5) with a daily cadence.
- In tests / dev: ``submit_task_run_cleanup()`` runs synchronously (eager
  mode) when called from a script or the health route.

We deliberately keep ``running`` / ``pending`` rows forever — those are
"stuck work" that a reviewer may need to chase down; we don't want the
cleanup cron to erase the evidence. Only ``succeeded`` / ``failed`` /
``canceled`` get pruned (adjustable via ``statuses`` arg).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models.task_run import TaskRun
from app.db.session import bypass_rls_session
from app.services.tasks import sink as task_sink
from app.workers.celery_app import celery_app

_log = logging.getLogger(__name__)


# Statuses we prune. Running / pending are excluded on purpose:
# they indicate unfinished or stuck work and still need attention.
DEFAULT_PRUNE_STATUSES = (
    task_sink.STATUS_SUCCEEDED,
    task_sink.STATUS_FAILED,
    task_sink.STATUS_CANCELED,
)


def cleanup_old_task_runs(
    *,
    retention_days: int | None = None,
    statuses: tuple[str, ...] = DEFAULT_PRUNE_STATUSES,
    now: datetime | None = None,
) -> int:
    """Delete terminal task_run rows older than the retention window.

    Returns the delete count. ``retention_days <= 0`` → no-op (tests /
    dev that don't want background mutation).
    """
    effective_days = (
        retention_days if retention_days is not None else get_settings().task_run_retention_days
    )
    if effective_days <= 0:
        return 0
    cutoff = (now or datetime.now(UTC)) - timedelta(days=effective_days)
    with bypass_rls_session() as session:
        result = session.execute(
            delete(TaskRun).where(TaskRun.created_at < cutoff).where(TaskRun.status.in_(statuses))
        )
        session.commit()
        count = int(result.rowcount or 0)
    if count:
        _log.info(
            "task_run_cleanup_completed",
            extra={
                "deleted_rows": count,
                "cutoff_days": effective_days,
                "statuses": list(statuses),
            },
        )
    return count


@celery_app.task(name="maintenance.cleanup_task_run")
def cleanup_old_task_runs_task() -> dict[str, int]:
    """Celery entry point for the daily cleanup."""
    deleted = cleanup_old_task_runs()
    return {"deleted_rows": deleted}


def submit_task_run_cleanup():
    """Kick off cleanup from non-Celery contexts (tests / manual).

    Uses ``.apply_async`` so eager mode runs inline, async mode queues.
    """
    return cleanup_old_task_runs_task.apply_async()


__all__ = [
    "DEFAULT_PRUNE_STATUSES",
    "cleanup_old_task_runs",
    "cleanup_old_task_runs_task",
    "submit_task_run_cleanup",
]
