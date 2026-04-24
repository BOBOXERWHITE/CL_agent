"""P5.5: task_run cleanup + Celery beat schedule tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.task_run import TaskRun
from app.db.session import SessionLocal
from app.services.tasks import sink as task_sink
from app.workers.maintenance import (
    cleanup_old_task_runs,
    cleanup_old_task_runs_task,
)


def _seed(
    *,
    task_id: str,
    status: str,
    created_at: datetime,
    tenant_id: str = "t1",
) -> None:
    with SessionLocal() as session:
        session.add(
            TaskRun(
                id=task_id,
                tenant_id=tenant_id,
                user_id="",
                task_name="knowledge.ingest_document",
                status=status,
                idempotency_key=None,
                input_json={},
                retries=0,
                trace_id="",
                summary="",
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()


def test_cleanup_deletes_old_succeeded_rows() -> None:
    now = datetime.now(UTC)
    _seed(task_id="old-s", status=task_sink.STATUS_SUCCEEDED, created_at=now - timedelta(days=120))
    _seed(task_id="new-s", status=task_sink.STATUS_SUCCEEDED, created_at=now - timedelta(days=10))

    deleted = cleanup_old_task_runs(retention_days=90, now=now)
    assert deleted == 1

    with SessionLocal() as session:
        ids = {row.id for row in session.query(TaskRun).all()}
    assert ids == {"new-s"}


def test_cleanup_preserves_running_rows_regardless_of_age() -> None:
    """Running / pending = unfinished work. Even if a ``running`` row
    is 100 days old (indicating stuck work) we must NOT delete it —
    reviewers need the evidence."""
    now = datetime.now(UTC)
    _seed(
        task_id="stuck",
        status=task_sink.STATUS_RUNNING,
        created_at=now - timedelta(days=120),
    )
    _seed(
        task_id="pending",
        status=task_sink.STATUS_PENDING,
        created_at=now - timedelta(days=120),
    )

    deleted = cleanup_old_task_runs(retention_days=90, now=now)
    assert deleted == 0
    with SessionLocal() as session:
        assert session.query(TaskRun).count() == 2


def test_cleanup_deletes_failed_and_canceled_too() -> None:
    now = datetime.now(UTC)
    _seed(task_id="f", status=task_sink.STATUS_FAILED, created_at=now - timedelta(days=100))
    _seed(task_id="c", status=task_sink.STATUS_CANCELED, created_at=now - timedelta(days=100))

    deleted = cleanup_old_task_runs(retention_days=90, now=now)
    assert deleted == 2


def test_cleanup_respects_retention_days() -> None:
    """Bigger retention → no rows deleted even if they'd be pruned
    under the default."""
    now = datetime.now(UTC)
    _seed(
        task_id="mid",
        status=task_sink.STATUS_SUCCEEDED,
        created_at=now - timedelta(days=45),
    )

    assert cleanup_old_task_runs(retention_days=30, now=now) == 1
    with SessionLocal() as session:
        assert session.query(TaskRun).count() == 0


def test_cleanup_zero_retention_is_noop() -> None:
    """``TASK_RUN_RETENTION_DAYS=0`` disables the cron so dev envs
    never have rows deleted."""
    now = datetime.now(UTC)
    _seed(
        task_id="x",
        status=task_sink.STATUS_SUCCEEDED,
        created_at=now - timedelta(days=9999),
    )

    assert cleanup_old_task_runs(retention_days=0, now=now) == 0
    with SessionLocal() as session:
        assert session.query(TaskRun).count() == 1


def test_celery_task_wraps_cleanup() -> None:
    """The Celery task entry just delegates to ``cleanup_old_task_runs``
    and returns the count. Verified via eager mode."""
    now = datetime.now(UTC)
    _seed(
        task_id="s-celery",
        status=task_sink.STATUS_SUCCEEDED,
        created_at=now - timedelta(days=200),
    )
    result = cleanup_old_task_runs_task.apply()
    assert not result.failed()
    payload = result.get()
    assert payload == {"deleted_rows": 1}


def test_beat_schedule_registers_cleanup() -> None:
    """``celery -A app.workers.celery_app beat`` must see the cleanup
    task — guard against accidental removal of the schedule entry."""
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule or {}
    assert "cleanup-task-run-daily" in schedule
    assert schedule["cleanup-task-run-daily"]["task"] == "maintenance.cleanup_task_run"


def test_custom_statuses_filter(session_isolate: None = None) -> None:
    """Caller can restrict the prune to a narrower status set."""
    now = datetime.now(UTC)
    _seed(task_id="s", status=task_sink.STATUS_SUCCEEDED, created_at=now - timedelta(days=100))
    _seed(task_id="f", status=task_sink.STATUS_FAILED, created_at=now - timedelta(days=100))

    # Only prune failed → success row survives.
    deleted = cleanup_old_task_runs(
        retention_days=90,
        statuses=(task_sink.STATUS_FAILED,),
        now=now,
    )
    assert deleted == 1
    with SessionLocal() as session:
        ids = {row.id for row in session.query(TaskRun).all()}
    assert ids == {"s"}


@pytest.fixture()
def session_isolate() -> None:
    """Just a marker so the test signature stays explicit."""
