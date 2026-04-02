from __future__ import annotations

from dataclasses import asdict

from app.core.config import get_settings
from app.services.ingestion.pipeline import run_ingestion_job
from app.workers.celery_app import celery_app


@celery_app.task(name="knowledge.ingest_document")
def ingest_document_task(document_id: str) -> dict[str, object]:
    return asdict(run_ingestion_job(document_id))


def submit_ingestion(document_id: str):
    if get_settings().celery_task_always_eager:
        return asdict(run_ingestion_job(document_id))
    return ingest_document_task.delay(document_id)
