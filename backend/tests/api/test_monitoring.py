from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DOCX_CONTENT_TYPE


@pytest.fixture()
def secured_client(monkeypatch: pytest.MonkeyPatch, _test_environment: None) -> Iterator[TestClient]:
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


def test_monitoring_overview_aggregates_current_business_state(
    secured_client: TestClient,
    docx_file: bytes,
) -> None:
    upload_response = secured_client.post(
        "/api/knowledge/upload",
        headers={"Authorization": "Bearer admin-token"},
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert upload_response.status_code == 202

    chat_response = secured_client.post(
        "/api/chat/ask",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "question": "北京酒店报销上限是多少？",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )
    assert chat_response.status_code == 200

    eval_response = secured_client.post(
        "/api/evals/runs",
        headers={"Authorization": "Bearer admin-token"},
        json={"dataset_name": "zh-policy-smoke"},
    )
    assert eval_response.status_code == 201

    monitoring_response = secured_client.get(
        "/api/monitoring/overview",
        headers={"Authorization": "Bearer operator-token"},
    )

    assert monitoring_response.status_code == 200
    payload = monitoring_response.json()
    assert payload["knowledge_summary"]["document_total"] == 1
    assert payload["knowledge_summary"]["completed_total"] == 1
    assert payload["chat_summary"]["session_total"] == 1
    assert payload["chat_summary"]["message_total"] == 2
    assert payload["eval_summary"]["last_24h_total"] >= 1
    assert payload["request_summary"]["last_hour_total"] >= 1
    assert "recent_activity" in payload


def test_reviewer_cannot_read_monitoring_overview(secured_client: TestClient) -> None:
    response = secured_client.get(
        "/api/monitoring/overview",
        headers={"Authorization": "Bearer reviewer-token"},
    )

    assert response.status_code == 403
