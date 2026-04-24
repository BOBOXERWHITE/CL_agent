"""Unit tests for the P4.4 ``task_run`` sink.

Tests run against a throwaway in-memory SQLite so every test is fully
isolated (no RLS on SQLite; the sink is dialect-agnostic).
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.task_run import TaskRun
from app.services.tasks import sink


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", future=True)
    from app.db.models import (  # noqa: F401
        agent,
        agent_event,
        agent_memory,
        audit_log,
        conversation,
        eval,
        knowledge,
        prompt_template,
        rag_recall_log,
        rule,
        runtime_log,
        system_setting,
        task_run,
    )

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def test_register_task_inserts_pending_row(session: Session) -> None:
    row = sink.register_task(
        session,
        task_id=str(uuid4()),
        tenant_id="t1",
        task_name="knowledge.ingest_document",
        user_id="alice",
        idempotency_key="doc-42",
        input_payload={"document_id": "d-42"},
        summary="Ingest document d-42",
    )
    session.commit()

    assert row.status == sink.STATUS_PENDING
    assert row.input_json == {"document_id": "d-42"}
    assert row.retries == 0
    assert row.finished_at is None


def test_register_task_dedupes_on_idempotency_key(session: Session) -> None:
    first = sink.register_task(
        session,
        task_id="task-1",
        tenant_id="t1",
        task_name="knowledge.ingest_document",
        idempotency_key="same-doc",
        input_payload={"document_id": "d-1"},
    )
    session.commit()

    # Second call with identical tuple → same row, NOT a new one.
    second = sink.register_task(
        session,
        task_id="task-2",
        tenant_id="t1",
        task_name="knowledge.ingest_document",
        idempotency_key="same-doc",
        input_payload={"document_id": "d-1"},
    )
    session.commit()

    assert first.id == second.id == "task-1"
    assert session.query(TaskRun).count() == 1


def test_empty_idempotency_key_allows_duplicates(session: Session) -> None:
    """Empty key = opt-out of dedupe. Callers that don't have a stable
    business id accept duplicate runs.
    """
    sink.register_task(
        session,
        task_id="t-a",
        tenant_id="t1",
        task_name="knowledge.ingest_document",
        idempotency_key="",
        input_payload={"document_id": "x"},
    )
    sink.register_task(
        session,
        task_id="t-b",
        tenant_id="t1",
        task_name="knowledge.ingest_document",
        idempotency_key="",
        input_payload={"document_id": "x"},
    )
    session.commit()

    assert session.query(TaskRun).count() == 2


def test_mark_running_updates_status_and_retries(session: Session) -> None:
    row = sink.register_task(
        session, task_id="t1", tenant_id="t1", task_name="n", idempotency_key=""
    )
    session.commit()

    updated = sink.mark_running(session, task_id=row.id, retries=2)
    session.commit()

    assert updated is not None
    assert updated.status == sink.STATUS_RUNNING
    assert updated.retries == 2


def test_mark_running_is_noop_after_terminal(session: Session) -> None:
    row = sink.register_task(
        session, task_id="t1", tenant_id="t1", task_name="n", idempotency_key=""
    )
    sink.mark_succeeded(session, task_id=row.id, result={"ok": True})
    session.commit()

    post = sink.mark_running(session, task_id=row.id)
    assert post is not None
    assert post.status == sink.STATUS_SUCCEEDED


def test_mark_succeeded_records_result_and_finished_at(session: Session) -> None:
    row = sink.register_task(
        session, task_id="t1", tenant_id="t1", task_name="n", idempotency_key=""
    )
    session.commit()

    updated = sink.mark_succeeded(session, task_id=row.id, result={"chunks": 10, "docs": 1})
    session.commit()

    assert updated is not None
    assert updated.status == sink.STATUS_SUCCEEDED
    assert updated.result_json == {"chunks": 10, "docs": 1}
    assert updated.error_json is None
    assert updated.finished_at is not None


def test_mark_failed_records_error_and_finished_at(session: Session) -> None:
    row = sink.register_task(
        session, task_id="t1", tenant_id="t1", task_name="n", idempotency_key=""
    )
    session.commit()

    updated = sink.mark_failed(
        session,
        task_id=row.id,
        error={"type": "ConnectionError", "message": "down"},
        retries=3,
    )
    session.commit()

    assert updated is not None
    assert updated.status == sink.STATUS_FAILED
    assert updated.error_json == {"type": "ConnectionError", "message": "down"}
    assert updated.retries == 3
    assert updated.finished_at is not None
    assert updated.result_json is None


def test_mark_canceled_is_idempotent(session: Session) -> None:
    row = sink.register_task(
        session, task_id="t1", tenant_id="t1", task_name="n", idempotency_key=""
    )
    session.commit()

    first = sink.mark_canceled(session, task_id=row.id, note="user ran out of time")
    first_finished_at = first.finished_at if first else None
    session.commit()

    second = sink.mark_canceled(session, task_id=row.id, note="retry click")
    session.commit()

    assert second is not None
    assert second.status == sink.STATUS_CANCELED
    # Idempotent: note / finished_at are preserved from the first call.
    assert second.finished_at == first_finished_at


def test_mark_running_missing_row_returns_none(session: Session) -> None:
    assert sink.mark_running(session, task_id="missing") is None
    assert sink.mark_succeeded(session, task_id="missing") is None
    assert sink.mark_failed(session, task_id="missing") is None
    assert sink.mark_canceled(session, task_id="missing") is None


def test_find_existing_scopes_by_tenant(session: Session) -> None:
    sink.register_task(
        session,
        task_id="t1-row",
        tenant_id="t1",
        task_name="n",
        idempotency_key="shared-key",
    )
    sink.register_task(
        session,
        task_id="t2-row",
        tenant_id="t2",
        task_name="n",
        idempotency_key="shared-key",
    )
    session.commit()

    # Same key, different tenants → two distinct rows.
    t1 = sink.find_existing(session, tenant_id="t1", task_name="n", idempotency_key="shared-key")
    t2 = sink.find_existing(session, tenant_id="t2", task_name="n", idempotency_key="shared-key")
    assert t1 is not None and t2 is not None
    assert t1.id == "t1-row"
    assert t2.id == "t2-row"
