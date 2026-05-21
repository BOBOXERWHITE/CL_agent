from __future__ import annotations

from collections.abc import Iterator

import pytest
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
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_admin_can_read_and_update_system_settings(secured_client: TestClient) -> None:
    read_response = secured_client.get(
        "/api/settings/system",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert read_response.status_code == 200
    assert read_response.json()["editable_settings"] == {
        "default_tenant_id": "default-tenant",
        "default_customer_id": "default-customer",
        "chat_top_k": 3,
        "chat_confidence_threshold": 0.2,
        "default_eval_dataset": "zh-policy-smoke",
        "agent_router_provider": "keyword",
        "chat_history_max_turns": 5,
    }

    update_response = secured_client.put(
        "/api/settings/system",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "default_tenant_id": "演示租户",
            "default_customer_id": "演示客户",
            "chat_top_k": 5,
            "chat_confidence_threshold": 0.35,
            "default_eval_dataset": "zh-policy-smoke",
            "agent_router_provider": "embedding",
            "chat_history_max_turns": 8,
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["editable_settings"]["default_tenant_id"] == "演示租户"
    assert update_response.json()["editable_settings"]["chat_top_k"] == 5
    assert update_response.json()["editable_settings"]["chat_confidence_threshold"] == 0.35
    assert update_response.json()["editable_settings"]["agent_router_provider"] == "embedding"
    assert update_response.json()["editable_settings"]["chat_history_max_turns"] == 8


def test_admin_cannot_save_unknown_router_provider(secured_client: TestClient) -> None:
    response = secured_client.put(
        "/api/settings/system",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "default_tenant_id": "演示租户",
            "default_customer_id": "演示客户",
            "chat_top_k": 5,
            "chat_confidence_threshold": 0.35,
            "default_eval_dataset": "zh-policy-smoke",
            "agent_router_provider": "magic",
            "chat_history_max_turns": 5,
        },
    )

    # Pydantic Literal rejects values outside ``llm | embedding | keyword``
    # so a typo'd payload never reaches the router strategy chain.
    assert response.status_code == 422


def test_operator_cannot_update_system_settings(secured_client: TestClient) -> None:
    response = secured_client.put(
        "/api/settings/system",
        headers={"Authorization": "Bearer operator-token"},
        json={
            "default_tenant_id": "演示租户",
            "default_customer_id": "演示客户",
            "chat_top_k": 5,
            "chat_confidence_threshold": 0.35,
            "default_eval_dataset": "zh-policy-smoke",
            "agent_router_provider": "keyword",
            "chat_history_max_turns": 5,
        },
    )

    assert response.status_code == 403
