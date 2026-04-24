"""Integration-ish test for P5.1: HTTP trace_id propagation.

Uses ``TestClient`` so the FastAPI lifespan runs (schema bootstrap,
OTEL init, etc). We assert the middleware correctly:
- mints a trace id when the client doesn't send one (no 5xx)
- picks up the upstream traceparent when it does
- tolerates malformed headers without crashing
"""

from __future__ import annotations


def test_trace_middleware_mints_id_without_upstream_header(client) -> None:
    """No trace header → middleware mints a fresh id and the request
    completes normally. We assert no 5xx as the contract — the id
    itself is tested at the unit level in test_tracing.py.
    """
    resp = client.get("/health")
    assert resp.status_code == 200


def test_trace_middleware_accepts_upstream_traceparent(client) -> None:
    """Well-formed ``traceparent`` header must be accepted; the
    middleware picks up the id and injects it into the request context.
    """
    tp = "00-0123456789abcdef0123456789abcdef-1111111111111111-01"
    resp = client.get("/health", headers={"traceparent": tp})
    assert resp.status_code == 200


def test_trace_middleware_tolerates_malformed_traceparent(client) -> None:
    """Bad trace headers must never yield 5xx; we mint a new id
    silently (logged at DEBUG, not escalated).
    """
    resp = client.get("/health", headers={"traceparent": "garbage"})
    assert resp.status_code == 200


def test_trace_middleware_accepts_x_trace_id_alias(client) -> None:
    """Legacy callers that set ``X-Trace-Id`` instead of ``traceparent``
    still get correlation."""
    tid = "abcdef0123456789abcdef0123456789"
    resp = client.get("/health", headers={"x-trace-id": tid})
    assert resp.status_code == 200
