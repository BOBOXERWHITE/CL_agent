"""P5-patch-A: trace_span attached to business hot paths.

The no-op layer makes spans assertable without OTLP: each
``trace_span(name, **attrs)`` logs a ``trace_span_closed`` record at
DEBUG level carrying the attrs dict. We snag those via a log capture
and assert on the span name + attrs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.observability import tracing
from app.db.base import Base
from app.db.models.agent import AgentRun, AgentThread
from app.services.agents.engine import EventType, TimelineEvent
from app.services.agents.event_sink import persist_agent_events


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
        token_usage,
    )

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def span_log_capture(monkeypatch):
    """Capture every ``trace_span_closed`` DEBUG record. Yields a list
    that accumulates span-close events for the duration of the test.

    P8: explicitly forces the no-op tracing path (patch
    ``_get_tracer_if_ready`` to return None) so these tests stay
    deterministic regardless of whether a sibling test in the same
    pytest run has already initialised the real OTEL SDK. Without
    this, the OTEL path takes over and no debug records are emitted.
    """
    from app.core.observability import tracing as _tracing

    monkeypatch.setattr(_tracing, "_get_tracer_if_ready", lambda: None)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.msg == "trace_span_closed":
                records.append(record)

    handler = _Capture()
    logger = logging.getLogger("app.core.observability.tracing")
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_trace_span_closed_emits_debug_record_with_attrs(span_log_capture) -> None:
    """Sanity: the no-op layer logs each span close with the attrs
    dict attached — the assertion primitive for the other tests."""
    with tracing.trace_span("test.business.span", tenant_id="t1") as span:
        span.set_attr("extra", 42)

    assert len(span_log_capture) == 1
    record = span_log_capture[0]
    assert getattr(record, "span_name", "") == "test.business.span"
    assert getattr(record, "attrs", {}) == {"tenant_id": "t1", "extra": 42}


def test_persist_agent_events_opens_named_span(session: Session, span_log_capture) -> None:
    """``persist_agent_events`` must emit an ``agent_event.persist``
    span carrying ``agent_run_id`` + ``event_count``."""
    run_id = str(uuid4())
    session.add(
        AgentThread(
            id=run_id,
            tenant_id="t1",
            customer_id="c1",
            domain="policy",
            specialist="policy_supervisor_agent",
            status="active",
        )
    )
    session.add(
        AgentRun(
            id=run_id,
            thread_id=run_id,
            tenant_id="t1",
            customer_id="c1",
            agent_name="x",
            route_name="x",
            status="completed",
            confidence=0.9,
            requires_human_review=False,
            input_json={},
            output_json={},
            timeline_json=[],
        )
    )
    session.flush()

    persist_agent_events(
        session,
        agent_run_id=run_id,
        tenant_id="t1",
        events=[
            TimelineEvent(sequence=0, event_type=EventType.NODE_START, node_name="x"),
            TimelineEvent(sequence=1, event_type=EventType.NODE_END, node_name="x"),
        ],
    )

    named = [r for r in span_log_capture if getattr(r, "span_name", "") == "agent_event.persist"]
    assert len(named) == 1
    attrs = getattr(named[0], "attrs", {})
    assert attrs.get("agent_run_id") == run_id
    assert attrs.get("tenant_id") == "t1"
    assert attrs.get("event_count") == 2


def test_trace_span_nesting_preserves_sibling_attrs(span_log_capture) -> None:
    """Two siblings under a parent must both close — the no-op layer
    shouldn't swallow an inner span's close event even if the outer
    span's context is still open.
    """
    with tracing.trace_span("outer", op="parent"):
        with tracing.trace_span("inner.a", op="child-a"):
            pass
        with tracing.trace_span("inner.b", op="child-b"):
            pass

    names = [getattr(r, "span_name", "") for r in span_log_capture]
    # Close order is inner.a, inner.b, outer.
    assert names == ["inner.a", "inner.b", "outer"]


def test_trace_span_exception_in_body_still_emits_close(
    span_log_capture,
) -> None:
    """The no-op layer's ``finally`` must fire even when the body
    raised — we do NOT want to lose trace coverage of failing paths."""
    with pytest.raises(ValueError):
        with tracing.trace_span("errorful", tenant_id="t"):
            raise ValueError("boom")

    named = [r for r in span_log_capture if getattr(r, "span_name", "") == "errorful"]
    assert len(named) == 1


def test_query_engine_has_rewrite_and_generate_spans() -> None:
    """Guard against accidental deletion of the rewrite + generate spans.

    P8.1: the answer-generation span was renamed from the generic
    ``policy_qa.generate`` to the OpenInference-spec'd ``llm.answer``
    (produced by ``llm_span(purpose="answer", ...)``). Phoenix /
    LangSmith / Arize all key off the ``llm.*`` naming convention so
    spans render with the right icon + cost panel. The rewrite span
    keeps its ``policy_qa.rewrite`` name because it isn't a leaf LLM
    call (it can be HyDE / paraphrase / no-op depending on settings).
    """
    import inspect

    from app.services.rag import query_engine

    source = inspect.getsource(query_engine)
    assert '"policy_qa.rewrite"' in source
    # The answer LLM call is now wrapped in llm_span(purpose="answer"),
    # which produces span name "llm.answer" via the f"llm.{purpose}" rule.
    assert 'purpose="answer"' in source
    assert "llm_span" in source


def test_ingestion_task_references_restore_helper() -> None:
    """``ingest_document_task`` must import & call
    ``restore_trace_from_celery_headers`` so worker-side spans join
    the web-side trace."""
    import inspect

    from app.workers import tasks as tasks_module

    source = inspect.getsource(tasks_module)
    assert "restore_trace_from_celery_headers" in source
    assert "ingestion.run_job" in source
    # And submit_ingestion must propagate the trace_id in headers.
    assert "celery_task_headers" in source
