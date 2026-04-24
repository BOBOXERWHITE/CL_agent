from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    celery_app = Celery("travel_ops_copilot")
    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        result_backend=settings.celery_result_backend,
        task_always_eager=settings.celery_task_always_eager,
        task_store_eager_result=False,
    )
    # P5.5: daily housekeeping cron. ``celery -A app.workers.celery_app beat``
    # runs this; regular workers pick up the task. Retention / enable
    # gating lives in the task itself (``TASK_RUN_RETENTION_DAYS=0``
    # makes the cleanup a no-op without stopping beat).
    celery_app.conf.beat_schedule = {
        "cleanup-task-run-daily": {
            "task": "maintenance.cleanup_task_run",
            # 03:15 UTC every day — low-traffic for most tenants.
            "schedule": crontab(hour=3, minute=15),
        },
    }
    # Ensure the task module gets imported so ``maintenance.cleanup_task_run``
    # is registered when beat fires the schedule. We keep this at the
    # factory level (not a top-level import) so circular deps stay out.
    celery_app.conf.imports = ("app.workers.tasks", "app.workers.maintenance")
    return celery_app


celery_app = create_celery_app()
