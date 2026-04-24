from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient


@pytest.fixture()
def secured_client(
    monkeypatch: pytest.MonkeyPatch, _test_environment: None
) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_ADMIN_TOKENS", "admin-token")
    monkeypatch.setenv("AUTH_OPERATOR_TOKENS", "operator-token")
    monkeypatch.setenv("AUTH_REVIEWER_TOKENS", "reviewer-token")

    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()

    error_router = APIRouter()

    @error_router.get("/test-error")
    def test_error() -> dict[str, str]:
        raise RuntimeError("boom")

    app.include_router(error_router)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_runtime_logs_capture_success_and_failure_requests(secured_client: TestClient) -> None:
    health_response = secured_client.get("/health", headers={"Authorization": "Bearer admin-token"})
    assert health_response.status_code == 200

    error_response = secured_client.get(
        "/test-error", headers={"Authorization": "Bearer admin-token"}
    )
    assert error_response.status_code == 500

    list_response = secured_client.get(
        "/api/logs/runtime",
        headers={"Authorization": "Bearer admin-token"},
        params={"limit": 10},
    )

    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) >= 2
    assert any(item["path"] == "/health" and item["status_code"] == 200 for item in items)
    assert any(item["path"] == "/test-error" and item["status_code"] == 500 for item in items)


def test_runtime_logs_support_filters_and_detail_lookup(secured_client: TestClient) -> None:
    response = secured_client.post(
        "/api/chat/ask",
        headers={"Authorization": "Bearer admin-token", "X-Request-ID": "req-chat-1"},
        json={
            "question": "北京酒店报销上限是多少？",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )
    assert response.status_code == 200

    filtered_response = secured_client.get(
        "/api/logs/runtime",
        headers={"Authorization": "Bearer operator-token"},
        params={"request_id": "req-chat-1", "tenant_id": "t1", "path": "/api/chat/ask", "limit": 5},
    )

    assert filtered_response.status_code == 200
    items = filtered_response.json()["items"]
    assert len(items) == 1
    assert items[0]["request_id"] == "req-chat-1"
    assert items[0]["tenant_id"] == "t1"
    assert items[0]["path"] == "/api/chat/ask"

    detail_response = secured_client.get(
        f"/api/logs/runtime/{items[0]['id']}",
        headers={"Authorization": "Bearer operator-token"},
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["request_id"] == "req-chat-1"


def test_reviewer_cannot_read_runtime_logs(secured_client: TestClient) -> None:
    response = secured_client.get(
        "/api/logs/runtime",
        headers={"Authorization": "Bearer reviewer-token"},
    )

    assert response.status_code == 403
