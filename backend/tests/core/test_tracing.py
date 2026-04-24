"""Unit tests for P5.1 trace context.

We focus on the always-on no-op layer; the optional OTEL bridge is only
exercised for "doesn't crash when libs are missing". Real OTLP round-trip
belongs in an integration test (goes to a running collector).
"""

from __future__ import annotations

import pytest

from app.core.observability import tracing


@pytest.fixture(autouse=True)
def _reset_trace_context() -> None:
    """Each test starts with a clean trace context (contextvar defaults
    leak between tests in a single worker otherwise).
    """
    tracing._TRACE_ID_CTX.set(None)  # type: ignore[attr-defined]
    tracing._TENANT_ID_CTX.set(None)  # type: ignore[attr-defined]


def test_new_trace_id_is_32_hex_chars() -> None:
    tid = tracing.new_trace_id()
    assert len(tid) == 32
    assert all(c in "0123456789abcdef" for c in tid)


def test_extract_trace_id_from_traceparent_header() -> None:
    headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    tid = tracing.extract_trace_id_from_headers(headers)
    assert tid == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_extract_trace_id_falls_back_to_x_trace_id_header() -> None:
    headers = {"x-trace-id": "abcdef0123456789abcdef0123456789"}
    assert tracing.extract_trace_id_from_headers(headers) == "abcdef0123456789abcdef0123456789"


def test_extract_trace_id_mints_new_when_no_header() -> None:
    tid = tracing.extract_trace_id_from_headers({})
    assert len(tid) == 32


def test_extract_trace_id_ignores_malformed_traceparent() -> None:
    """A malformed traceparent shouldn't crash — we just mint a new id
    so the rest of the pipeline is unaffected."""
    headers = {"traceparent": "00-not-hex-at-all-01"}
    tid = tracing.extract_trace_id_from_headers(headers)
    assert len(tid) == 32  # fresh


def test_set_and_current_trace_id_roundtrip() -> None:
    tracing.set_trace_id("a" * 32)
    assert tracing.current_trace_id() == "a" * 32


def test_to_traceparent_round_trips_trace_id() -> None:
    tid = "0123456789abcdef0123456789abcdef"
    header = tracing.to_traceparent(tid)
    assert header is not None
    parts = header.split("-")
    assert parts[0] == "00"
    assert parts[1] == tid
    assert len(parts[2]) == 16
    assert parts[3] == "01"


def test_to_traceparent_rejects_bad_trace_id() -> None:
    assert tracing.to_traceparent("not-hex") is None
    assert tracing.to_traceparent(None) is None
    assert tracing.to_traceparent("") is None


def test_trace_span_noop_layer_accumulates_attrs() -> None:
    """Without OTEL libs configured, ``trace_span`` still accepts attrs
    and exposes them via the handle — tests can assert on business
    semantics even in the no-op path.
    """
    with tracing.trace_span("demo", tenant_id="t1") as span:
        span.set_attr("citation_count", 3)
    assert span.name == "demo"
    assert span.attrs == {"tenant_id": "t1", "citation_count": 3}


def test_trace_span_survives_exception_in_body() -> None:
    """A raising body must not leak state — next ``trace_span`` still works."""
    with pytest.raises(ValueError):
        with tracing.trace_span("risky"):
            raise ValueError("boom")
    # Next span still works.
    with tracing.trace_span("recovery") as span:
        span.set_attr("ok", True)
    assert span.attrs == {"ok": True}


def test_init_otel_tracer_is_noop_when_endpoint_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``OTEL_EXPORTER_OTLP_ENDPOINT`` = tracer stays no-op, no crash."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert tracing.init_otel_tracer() is False
    # Subsequent trace_span still works.
    with tracing.trace_span("still-works") as span:
        span.set_attr("x", 1)
    assert span.attrs == {"x": 1}


def test_celery_header_round_trip_preserves_trace_id() -> None:
    tid = "deadbeefdeadbeefdeadbeefdeadbeef"
    tracing.set_trace_id(tid)
    headers = tracing.celery_task_headers()
    assert headers == {"x_trace_id": tid}

    # Simulate worker side: clear context, restore from headers.
    tracing._TRACE_ID_CTX.set(None)  # type: ignore[attr-defined]
    restored = tracing.restore_trace_from_celery_headers(headers)
    assert restored == tid
    assert tracing.current_trace_id() == tid


def test_restore_trace_from_celery_headers_tolerates_missing_key() -> None:
    assert tracing.restore_trace_from_celery_headers(None) is None
    assert tracing.restore_trace_from_celery_headers({}) is None
    assert tracing.restore_trace_from_celery_headers({"other": "val"}) is None


def test_restore_trace_from_celery_headers_rejects_malformed_id() -> None:
    assert tracing.restore_trace_from_celery_headers({"x_trace_id": "short"}) is None
    assert tracing.current_trace_id() is None


def test_parse_otlp_headers_extracts_pairs() -> None:
    parsed = tracing._parse_otlp_headers("api-key=abc, x-org=foo")
    assert parsed == {"api-key": "abc", "x-org": "foo"}


def test_parse_otlp_headers_ignores_malformed_pairs() -> None:
    parsed = tracing._parse_otlp_headers("api-key=abc,bad_pair,key2=val2")
    assert parsed == {"api-key": "abc", "key2": "val2"}
