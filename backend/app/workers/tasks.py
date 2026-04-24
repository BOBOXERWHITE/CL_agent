from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict
from uuid import uuid4

from app.core.config import get_settings
from app.db.session import bypass_rls_session
from app.services.ingestion.pipeline import run_ingestion_job
from app.services.tasks import sink as task_sink
from app.workers.celery_app import celery_app

_log = logging.getLogger(__name__)

# P4.3 retry policy
# -----------------
# ``autoretry_for`` catches transient infra failures (network flaps,
# embedding gateway 5xx, Milvus temporarily unavailable) and retries
# with exponential backoff. The policy deliberately excludes
# ``ValueError`` / ``TypeError`` / ``KeyError`` because those almost
# always indicate programmer error or bad input — retrying those would
# just waste quota.
#
# ``retry_backoff=2`` + ``retry_backoff_max=60`` + ``max_retries=3``
# produces a ladder of 2s → 4s → 8s (capped at 60s). Small enough to
# mask a 5s upstream glitch, big enough to survive a minute-long
# restart.
#
# ``retry_jitter=True`` spreads out simultaneously-failed retries so
# the broker doesn't eat a thundering-herd reconnect storm.
_RETRYABLE_EXCEPTIONS = (ConnectionError, TimeoutError, OSError, RuntimeError)


def _ingestion_idempotency_key(document_id: str) -> str:
    """Stable dedupe key for ``submit_ingestion`` (P4.4).

    Identical ``document_id`` must map to the same key across processes
    and across pod restarts. SHA-256 first 32 chars gives collision
    headroom without a 64-char primary key.
    """
    digest = hashlib.sha256(f"ingest|{document_id}".encode()).hexdigest()
    return digest[:32]


@celery_app.task(
    name="knowledge.ingest_document",
    bind=True,
    autoretry_for=_RETRYABLE_EXCEPTIONS,
    retry_backoff=2,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def ingest_document_task(self, document_id: str) -> dict[str, object]:
    """Celery entry for the ingestion pipeline.

    Bound (``bind=True``) so we can log which retry attempt this is —
    observability for operators staring at a flaky embedder. The return
    value is the same ``IngestionJobResult`` dict the eager path would
    produce, so ``submit_ingestion`` callers that inspected the response
    keep working.

    P4.4: the task is also responsible for updating its ``task_run``
    row so the dashboard can show state transitions live. Celery task
    id = ``task_run.id``; workers have no request tenant so they use
    ``bypass_rls_session``.

    P5-patch-A: restores the trace_id from Celery headers so a document
    upload's trace in the OTLP backend joins the web-side trace; wraps
    the pipeline in a span so "ingestion took X ms" shows up alongside
    chat / agent spans.
    """
    from app.core.observability.tracing import (
        restore_trace_from_celery_headers,
        trace_span,
    )

    # Celery stores publish-time kwargs on self.request.headers under
    # v5; restore the trace_id here so every bypass_rls_session and log
    # call within this task correlates with the HTTP upload that
    # submitted it.
    headers = getattr(self.request, "headers", None) if hasattr(self, "request") else None
    restore_trace_from_celery_headers(headers)

    retries = getattr(self.request, "retries", 0) if hasattr(self, "request") else 0
    task_id = getattr(self.request, "id", None) if hasattr(self, "request") else None
    if retries:
        _log.info(
            "celery_task_retry",
            extra={
                "task_name": "knowledge.ingest_document",
                "document_id": document_id,
                "attempt": retries,
            },
        )
    if task_id:
        with bypass_rls_session() as session:
            task_sink.mark_running(session, task_id=task_id, retries=retries)
            session.commit()

    try:
        with trace_span(
            "ingestion.run_job",
            document_id=document_id,
            retry_attempt=retries,
        ):
            result = run_ingestion_job(document_id)
    except Exception as exc:
        # mark_failed only fires on the LAST retry — if Celery is going
        # to retry us, let it; we'll update the row on the next
        # mark_running. Detect terminality by comparing retries against
        # the configured max.
        max_retries = ingest_document_task.max_retries
        if task_id and retries >= max_retries:
            with bypass_rls_session() as session:
                task_sink.mark_failed(
                    session,
                    task_id=task_id,
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    retries=retries,
                )
                session.commit()
        raise

    payload = asdict(result)
    if task_id:
        with bypass_rls_session() as session:
            task_sink.mark_succeeded(session, task_id=task_id, result=payload)
            session.commit()
    return payload


def submit_ingestion(
    document_id: str,
    *,
    tenant_id: str = "",
    user_id: str = "",
    trace_id: str = "",
):
    """Kick off (or dedupe) a document ingestion.

    Behavior matrix:

    - Eager mode (tests / default dev): run inline, still register the
      task_run for observability parity.
    - Celery mode: register a ``pending`` task_run, hand the task to the
      broker; the worker will update the row as it progresses.

    Idempotency: two ``submit_ingestion(document_id="d")`` calls with the
    same tenant_id + doc return the **same** task_run id. The caller
    still gets a dict-shape response in eager mode so legacy callers
    don't break.
    """
    settings = get_settings()
    idempotency_key = _ingestion_idempotency_key(document_id)
    task_id = str(uuid4())

    with bypass_rls_session() as session:
        row = task_sink.register_task(
            session,
            task_id=task_id,
            tenant_id=tenant_id,
            task_name="knowledge.ingest_document",
            user_id=user_id,
            idempotency_key=idempotency_key,
            input_payload={"document_id": document_id},
            trace_id=trace_id,
            summary=f"Ingest document {document_id}",
        )
        session.commit()
        task_id = row.id
        existing_status = row.status
        cached_result = dict(row.result_json or {})

    # If we hit a duplicate that already succeeded, short-circuit: no
    # need to run ingestion again. This is the main P4.4 win for the
    # "user accidentally uploads twice" case.
    if existing_status == task_sink.STATUS_SUCCEEDED and cached_result:
        return cached_result

    if settings.celery_task_always_eager:
        try:
            result = run_ingestion_job(document_id)
        except Exception as exc:
            with bypass_rls_session() as session:
                task_sink.mark_failed(
                    session,
                    task_id=task_id,
                    error={"type": type(exc).__name__, "message": str(exc)},
                )
                session.commit()
            raise
        payload = asdict(result)
        with bypass_rls_session() as session:
            task_sink.mark_succeeded(session, task_id=task_id, result=payload)
            session.commit()
        return payload

    # Async broker path: hand the task the pre-allocated task_run id so
    # the worker updates the same row. Also carry the current trace_id
    # via Celery headers so the worker-side span joins the web-side
    # trace (P5-patch-A).
    from app.core.observability.tracing import celery_task_headers

    return ingest_document_task.apply_async(
        args=(document_id,),
        task_id=task_id,
        headers=celery_task_headers() or None,
    )
