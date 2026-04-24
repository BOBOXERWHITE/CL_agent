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


def test_operator_without_admin_role_cannot_edit_prompt_template(
    secured_client: TestClient,
) -> None:
    response = secured_client.post(
        "/api/prompts",
        headers={"Authorization": "Bearer operator-token"},
        json={
            "name": "运营默认 Prompt",
            "task_type": "policy_answer",
            "template": "请基于引用回答。",
        },
    )

    assert response.status_code == 403


def test_admin_can_edit_prompt_template(secured_client: TestClient) -> None:
    response = secured_client.post(
        "/api/prompts",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "name": "管理员 Prompt",
            "task_type": "policy_answer",
            "template": "请基于引用回答。",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_reviewer_can_view_review_queue(secured_client: TestClient) -> None:
    response = secured_client.get(
        "/api/reviews/queue",
        headers={"Authorization": "Bearer reviewer-token"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
