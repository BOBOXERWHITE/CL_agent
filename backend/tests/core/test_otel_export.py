"""P5-patch-C: end-to-end OTEL SDK plumbing test.

Uses ``InMemorySpanExporter`` (part of ``opentelemetry-sdk``) as an
injected exporter so we can verify the full chain without a real
collector:

    trace_span(name, **attrs)
        ↓
    TracerProvider.start_as_current_span
        ↓
    SimpleSpanProcessor
        ↓
    InMemorySpanExporter.export() (buffered)

Failure modes we're guarding against:
- OTEL SDK breaking change (upgrade from 1.29 to 1.30 rewording
  attribute API, removing SpanProcessor methods, etc.)
- ``trace_span`` accidentally not forwarding attrs to the real span
- Nesting semantics regressing (parent-child relationships lost)

If ``opentelemetry-sdk`` isn't installed this whole test module is
skipped — consistent with the sibling ``.[otel]`` extra being optional.
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.core.observability import tracing

# OTEL's ``set_tracer_provider`` is a one-shot: subsequent calls log a
# warning and keep the original provider. So we init once (module
# scope) and clear the exporter's buffer between tests.
_SHARED_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _otel_module_setup():
    """Init the OTEL SDK with our in-memory exporter once per module."""
    tracing.init_otel_tracer(exporter=_SHARED_EXPORTER, force=True)
    yield
    tracing.shutdown_otel_tracer()


@pytest.fixture()
def exporter() -> InMemorySpanExporter:
    """Provide a clean exporter state to each test (buffer cleared)."""
    _SHARED_EXPORTER.clear()
    return _SHARED_EXPORTER


def test_trace_span_reaches_exporter(exporter: InMemorySpanExporter) -> None:
    """A single ``trace_span`` call must land a span in the in-memory
    exporter with the right name and attrs."""
    with tracing.trace_span("test.basic", tenant_id="t1") as span:
        span.set_attr("extra_attr", 7)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "test.basic"
    attrs = dict(s.attributes or {})
    assert attrs.get("tenant_id") == "t1"
    assert attrs.get("extra_attr") == 7


def test_nested_trace_spans_preserve_parent_child(
    exporter: InMemorySpanExporter,
) -> None:
    """Child span must have the parent's span_id as its parent — proof
    that trace_span uses ``start_as_current_span`` correctly."""
    with tracing.trace_span("outer", stage="request"):
        with tracing.trace_span("inner", stage="retrieval"):
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    by_name = {s.name: s for s in spans}
    inner = by_name["inner"]
    outer = by_name["outer"]
    # Inner's parent_span_id must match outer's span_id.
    assert inner.parent is not None
    assert inner.parent.span_id == outer.context.span_id
    # Both share the same trace_id.
    assert inner.context.trace_id == outer.context.trace_id


def test_exception_in_span_marks_error_status(
    exporter: InMemorySpanExporter,
) -> None:
    """A raising body must produce an ERROR-status span (for alerting
    dashboards that want "show me failing spans")."""
    with pytest.raises(ValueError):
        with tracing.trace_span("errorful"):
            raise ValueError("boom")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    # OTEL StatusCode ERROR = 2; StatusCode OK = 1; UNSET = 0.
    from opentelemetry.trace import StatusCode

    assert s.status.status_code == StatusCode.ERROR


def test_init_otel_tracer_is_idempotent_without_force(
    exporter: InMemorySpanExporter,
) -> None:
    """A second ``init_otel_tracer`` call without ``force=True`` must
    be a no-op — production lifespans that accidentally call it twice
    must not clobber the tracer."""
    # Module fixture already initialised; a second call returns True
    # (already ready) and doesn't touch the SDK.
    assert tracing.init_otel_tracer(exporter=InMemorySpanExporter()) is True

    # Spans still go to the original exporter.
    with tracing.trace_span("still-here"):
        pass
    assert len(exporter.get_finished_spans()) == 1


def test_business_span_via_policy_qa_helpers(
    exporter: InMemorySpanExporter,
) -> None:
    """Call ``persist_agent_events`` (which wraps its body in an
    ``agent_event.persist`` span) and confirm the OTLP-side span lands
    in the exporter with the expected attrs."""
    from collections.abc import Iterator
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from app.db.base import Base
    from app.db.models.agent import AgentRun, AgentThread
    from app.services.agents.engine import EventType, TimelineEvent
    from app.services.agents.event_sink import persist_agent_events

    def _session() -> Iterator[Session]:
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
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        yield factory()

    session = next(_session())
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
        ],
    )

    names = [s.name for s in exporter.get_finished_spans()]
    assert "agent_event.persist" in names
    target = next(s for s in exporter.get_finished_spans() if s.name == "agent_event.persist")
    attrs = dict(target.attributes or {})
    assert attrs.get("agent_run_id") == run_id
    assert attrs.get("tenant_id") == "t1"
    assert attrs.get("event_count") == 1
