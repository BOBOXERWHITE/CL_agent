"""Celery task retry / backoff policy tests (P4.3).

Tests run with ``CELERY_TASK_ALWAYS_EAGER=true`` (the test fixture
default) so ``task.apply()`` actually executes the task inline. Eager
mode *does* support ``autoretry_for`` + ``max_retries``, so we can
verify the retry ladder without a real broker.

What we pin
-----------

1. **Retryable exceptions DO retry**: ``ConnectionError`` bubbles up
   ``max_retries + 1`` times (3 retries + 1 initial attempt = 4 calls).
2. **Non-retryable exceptions DO NOT retry**: ``ValueError`` is not in
   ``_RETRYABLE_EXCEPTIONS`` and fails immediately (1 call).
3. **Success stops retrying**: succeed on the 2nd attempt, we see
   exactly 2 calls, not 4.
4. **Task configuration** advertises retries on at import time — so
   operators running ``celery inspect registered`` see the policy.
"""

from __future__ import annotations

from unittest.mock import patch


def test_retryable_exception_is_retried_up_to_max_retries() -> None:
    from app.workers.tasks import ingest_document_task

    attempt_count = {"value": 0}

    def _fail_every_time(document_id: str):
        attempt_count["value"] += 1
        raise ConnectionError("simulated upstream failure")

    with patch("app.workers.tasks.run_ingestion_job", side_effect=_fail_every_time):
        result = ingest_document_task.apply(args=("doc-1",))
    # ``result.failed()`` is True because all retries exhausted.
    assert result.failed()
    # max_retries=3 + initial attempt = 4 total calls.
    assert attempt_count["value"] == 4


def test_non_retryable_exception_fails_fast() -> None:
    """``ValueError`` is a programmer error, not infra flakiness. It
    must NOT be retried — retrying bad input wastes quota without any
    chance of succeeding.
    """
    from app.workers.tasks import ingest_document_task

    attempt_count = {"value": 0}

    def _fail_with_value_error(document_id: str):
        attempt_count["value"] += 1
        raise ValueError("bad document id")

    with patch("app.workers.tasks.run_ingestion_job", side_effect=_fail_with_value_error):
        result = ingest_document_task.apply(args=("doc-1",))
    assert result.failed()
    # Exactly one attempt. No retries.
    assert attempt_count["value"] == 1


def test_transient_failure_then_success_retries_until_ok() -> None:
    """Succeed on the 2nd try → 2 calls total; the ``IngestionJobResult``
    bubbles back as the return value."""
    from dataclasses import dataclass

    from app.workers.tasks import ingest_document_task

    @dataclass
    class _FakeJobResult:
        document_id: str
        status: str

    attempt_count = {"value": 0}

    def _flaky(document_id: str):
        attempt_count["value"] += 1
        if attempt_count["value"] == 1:
            raise ConnectionError("transient glitch")
        return _FakeJobResult(document_id=document_id, status="success")

    with patch("app.workers.tasks.run_ingestion_job", side_effect=_flaky):
        result = ingest_document_task.apply(args=("doc-2",))

    assert not result.failed()
    payload = result.get()
    assert payload == {"document_id": "doc-2", "status": "success"}
    assert attempt_count["value"] == 2


def test_task_is_registered_with_retry_config() -> None:
    """Pin the retry policy at the signature level so accidental
    edits to ``@celery_app.task(...)`` don't silently break it.
    ``celery inspect registered`` would show these values to operators.
    """
    from app.workers.tasks import ingest_document_task

    # Celery stores task-level config on the registered task object.
    # We check the three knobs the plan doc promised.
    assert ingest_document_task.max_retries == 3
    assert ingest_document_task.retry_backoff == 2
    assert ingest_document_task.retry_backoff_max == 60
    assert ingest_document_task.retry_jitter is True
    # Retryable set includes infra errors and excludes programmer errors.
    assert ConnectionError in ingest_document_task.autoretry_for
    assert TimeoutError in ingest_document_task.autoretry_for
    assert ValueError not in ingest_document_task.autoretry_for


def test_submit_ingestion_still_returns_dict_in_eager_mode() -> None:
    """Backward-compat: the ``submit_ingestion`` return shape must stay
    a plain dict when eager mode is on (API callers that inspected the
    response must not break)."""
    from dataclasses import dataclass

    from app.workers import tasks as tasks_module

    @dataclass
    class _FakeJobResult:
        document_id: str
        status: str
        chunk_count: int = 3

    with patch.object(tasks_module, "run_ingestion_job", return_value=_FakeJobResult("d1", "ok")):
        result = tasks_module.submit_ingestion("d1", tenant_id="t1")
    assert isinstance(result, dict)
    assert result["document_id"] == "d1"


def test_submit_ingestion_dedupes_on_second_submit_after_success() -> None:
    """Second ``submit_ingestion`` with identical tenant+doc must NOT
    re-run the ingestion pipeline — it returns the cached result from
    the first run's ``task_run`` row. This is the P4.4 "user uploaded
    twice" protection.
    """
    from dataclasses import dataclass

    from app.workers import tasks as tasks_module

    @dataclass
    class _FakeJobResult:
        document_id: str
        status: str = "ok"

    call_count = {"value": 0}

    def _counting(document_id: str):
        call_count["value"] += 1
        return _FakeJobResult(document_id=document_id)

    with patch.object(tasks_module, "run_ingestion_job", side_effect=_counting):
        first = tasks_module.submit_ingestion("doc-dedup", tenant_id="t-dedup")
        second = tasks_module.submit_ingestion("doc-dedup", tenant_id="t-dedup")

    # Only the first call runs the pipeline; the second short-circuits.
    assert call_count["value"] == 1
    assert first == second
    assert first["document_id"] == "doc-dedup"


def test_submit_ingestion_different_tenants_do_not_dedupe() -> None:
    """Same doc across two tenants must run twice — the idempotency key
    is scoped to ``(tenant_id, task_name, idempotency_key)``.
    """
    from dataclasses import dataclass

    from app.workers import tasks as tasks_module

    @dataclass
    class _FakeJobResult:
        document_id: str
        status: str = "ok"

    call_count = {"value": 0}

    def _counting(document_id: str):
        call_count["value"] += 1
        return _FakeJobResult(document_id=document_id)

    with patch.object(tasks_module, "run_ingestion_job", side_effect=_counting):
        tasks_module.submit_ingestion("shared-doc", tenant_id="tenant-a")
        tasks_module.submit_ingestion("shared-doc", tenant_id="tenant-b")

    assert call_count["value"] == 2
