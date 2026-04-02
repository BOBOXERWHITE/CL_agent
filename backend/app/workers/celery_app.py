from __future__ import annotations

from celery import Celery

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
    return celery_app


celery_app = create_celery_app()
