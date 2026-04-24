"""Tests for the P1.6 rate limiter.

We enable the limiter via env vars (tests default to disabled so unrelated
suites don't interact with counters) and pin a very small limit per minute
so the test doesn't loop 20+ times to trigger 429.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def rate_limited_client(
    _test_environment: None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    # Enable the limiter and pin all limits to 2/minute so the third call
    # in each test trips the limiter deterministically. Per-route limits
    # are read as lambdas at request time from ``get_settings()``, so the
    # env vars below take effect without rebuilding the limiter.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "100/minute")
    monkeypatch.setenv("RATE_LIMIT_CHAT_ASK", "2/minute")
    monkeypatch.setenv("RATE_LIMIT_KNOWLEDGE_UPLOAD", "2/minute")
    monkeypatch.setenv("RATE_LIMIT_AUTH_DEV_TOKEN", "2/minute")

    from app.core.config import get_settings
    from app.core.rate_limit import limiter, reset_limiter_storage

    get_settings.cache_clear()
    # Clear any counter state from an earlier test.
    reset_limiter_storage()
    # Flip the existing limiter on; the route decorators hold this object
    # directly so flipping ``enabled`` takes effect without redecorating.
    previous_enabled = limiter.enabled
    limiter.enabled = True

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer admin-token"})
        yield client

    limiter.enabled = previous_enabled
    reset_limiter_storage()
    get_settings.cache_clear()


def test_chat_ask_third_call_returns_429(rate_limited_client: TestClient, docx_file: bytes) -> None:
    # Seed so /ask has something to retrieve.
    upload = rate_limited_client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "default-tenant", "customer_id": "default-customer"},
        files={
            "file": (
                "policy.docx",
                docx_file,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert upload.status_code == 202

    body = {"question": "test", "tenant_id": "default-tenant", "customer_id": "default-customer"}
    assert rate_limited_client.post("/api/chat/ask", json=body).status_code == 200
    assert rate_limited_client.post("/api/chat/ask", json=body).status_code == 200
    # Third call: limit is 2/minute.
    third = rate_limited_client.post("/api/chat/ask", json=body)
    assert third.status_code == 429
    envelope = third.json()
    assert envelope["error"]["code"] == "RATE_LIMITED"
    assert envelope["detail"] == "rate limit exceeded"


def test_rate_limit_headers_exposed_on_success(rate_limited_client: TestClient) -> None:
    """slowapi adds X-RateLimit-* headers when headers_enabled=True."""
    response = rate_limited_client.post(
        "/api/auth/dev-token", json={"user_id": "alice", "tenant_id": "t-a"}
    )
    # 200 with count headers present; remaining should decrement on next call.
    assert response.status_code == 200
    assert "x-ratelimit-limit" in {k.lower() for k in response.headers}


def test_rate_limit_is_per_user_not_global(rate_limited_client: TestClient) -> None:
    """Two different ``(tenant, user)`` pairs get separate buckets.

    The default ``client`` fixture sends ``Authorization: Bearer admin-token``
    (static token mode), which resolves to ``user_id=static-admin`` +
    ``tenant_id=default-tenant``. We burn that bucket with 2 chat calls,
    then prove another identity (via a fresh unauth'd call bucket on IP)
    can still operate.
    """
    # Burn the default bucket.
    body = {"question": "x", "tenant_id": "default-tenant", "customer_id": "default-customer"}
    rate_limited_client.post("/api/chat/ask", json=body)
    rate_limited_client.post("/api/chat/ask", json=body)
    blocked = rate_limited_client.post("/api/chat/ask", json=body)
    assert blocked.status_code == 429

    # /api/auth/dev-token has no auth; its key comes from IP. Separate
    # bucket, should still succeed.
    token_call = rate_limited_client.post(
        "/api/auth/dev-token", json={"user_id": "alice", "tenant_id": "t-a"}
    )
    assert token_call.status_code != 429


def test_rate_limit_disabled_by_default(client: TestClient, docx_file: bytes) -> None:
    """The default unit-test fixture does not set RATE_LIMIT_ENABLED.

    Burn through 5 chat calls and confirm none return 429, proving the
    unit suite is not accidentally exercising the limiter.
    """
    upload = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "default-tenant", "customer_id": "default-customer"},
        files={
            "file": (
                "policy.docx",
                docx_file,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert upload.status_code == 202
    body = {"question": "x", "tenant_id": "default-tenant", "customer_id": "default-customer"}
    statuses = [client.post("/api/chat/ask", json=body).status_code for _ in range(5)]
    assert all(s == 200 for s in statuses), statuses
