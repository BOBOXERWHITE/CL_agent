"""P7.4: ``/api/health/slo`` rolling-window snapshot tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models.runtime_log import RuntimeLog
from app.db.session import SessionLocal


def _seed_run(
    *,
    latency_ms: int,
    status_code: int = 200,
    tenant_id: str | None = "default-tenant",
    session_id: str | None = None,
    created_at: datetime | None = None,
) -> None:
    with SessionLocal() as session:
        session.add(
            RuntimeLog(
                id=str(uuid4()),
                request_id=str(uuid4()),
                method="POST",
                path="/api/chat/ask",
                status_code=status_code,
                latency_ms=latency_ms,
                tenant_id=tenant_id,
                customer_id="c1",
                session_id=session_id,
                user_role="operator",
                model_name="m",
                token_usage_json={},
                error_message=None,
                created_at=created_at or datetime.now(UTC),
            )
        )
        session.commit()


def test_slo_snapshot_empty_window(client: TestClient) -> None:
    """Fresh test DB → no rows → request_count=0, percentiles null."""
    resp = client.get("/api/health/slo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["request_count"] == 0
    assert body["p50_latency_ms"] is None
    assert body["p95_latency_ms"] is None
    assert body["error_rate"] is None
    assert body["active_chat_sessions"] == 0


def test_slo_snapshot_computes_p50_p95(client: TestClient) -> None:
    """5 runtime_log rows with latencies 100..500 → p50≈300, p95≈480."""
    for latency in (100, 200, 300, 400, 500):
        _seed_run(latency_ms=latency)

    resp = client.get("/api/health/slo")
    body = resp.json()
    assert body["request_count"] == 5
    # Sorted [100,200,300,400,500]; p50 (inclusive interp) lands on 300.
    assert body["p50_latency_ms"] == 300
    # p95 between 400 and 500 — for 5 points it's 480.
    assert body["p95_latency_ms"] == 480


def test_slo_snapshot_error_rate(client: TestClient) -> None:
    for _ in range(8):
        _seed_run(latency_ms=100, status_code=200)
    for _ in range(2):
        _seed_run(latency_ms=100, status_code=500)

    resp = client.get("/api/health/slo")
    body = resp.json()
    assert body["request_count"] == 10
    assert body["error_rate"] == 0.2


def test_slo_snapshot_filters_by_window(client: TestClient) -> None:
    """Rows older than the window must not be counted."""
    now = datetime.now(UTC)
    _seed_run(latency_ms=100, created_at=now - timedelta(minutes=30))
    _seed_run(latency_ms=200, created_at=now - timedelta(minutes=2))

    # 5-minute window: only the recent row counts.
    resp = client.get("/api/health/slo", params={"window_minutes": 5})
    body = resp.json()
    assert body["request_count"] == 1
    assert body["p50_latency_ms"] == 200


def test_slo_snapshot_counts_distinct_sessions(client: TestClient) -> None:
    # Two sessions × 2 requests each.
    _seed_run(latency_ms=100, session_id="sess-a")
    _seed_run(latency_ms=150, session_id="sess-a")
    _seed_run(latency_ms=120, session_id="sess-b")
    # A request with no session shouldn't count.
    _seed_run(latency_ms=80, session_id=None)

    resp = client.get("/api/health/slo")
    body = resp.json()
    assert body["active_chat_sessions"] == 2


def test_slo_snapshot_requires_admin_or_operator(client: TestClient) -> None:
    resp = client.get(
        "/api/health/slo",
        headers={"Authorization": "Bearer reviewer-token"},
    )
    assert resp.status_code == 403


def test_slo_window_parameter_bounds(client: TestClient) -> None:
    # 0 / negative rejected by Query(ge=1)
    resp = client.get("/api/health/slo", params={"window_minutes": 0})
    assert resp.status_code == 422
    # >60 rejected
    resp = client.get("/api/health/slo", params={"window_minutes": 120})
    assert resp.status_code == 422
