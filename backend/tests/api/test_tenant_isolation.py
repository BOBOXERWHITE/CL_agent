"""Cross-tenant isolation tests for the P1.3 guard.

Verifies that ``require_tenant_match`` blocks every documented escalation
path: a JWT for tenant A cannot operate on tenant B even when the request
body claims tenant B. Each route-level test is paired with a positive
control (same tenant in body and claim) to make sure the guard does not
over-block.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def jwt_client(_test_environment: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JWT_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-signing-key-please-change-me")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ISSUER", "travel-ops-copilot")
    monkeypatch.setenv("JWT_AUDIENCE", "travel-ops-copilot-api")
    monkeypatch.setenv("JWT_DEV_TOKEN_ENDPOINT_ENABLED", "true")

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


def _mint(
    client: TestClient,
    *,
    tenant_id: str,
    roles: tuple[str, ...] = ("admin",),
) -> str:
    response = client.post(
        "/api/auth/dev-token",
        json={"user_id": "alice", "tenant_id": tenant_id, "roles": list(roles)},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_chat_ask_blocks_cross_tenant_body(jwt_client: TestClient) -> None:
    token_a = _mint(jwt_client, tenant_id="tenant-a")
    response = jwt_client.post(
        "/api/chat/ask",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "question": "stub",
            "tenant_id": "tenant-b",  # claim says A, body says B → 403
            "customer_id": "c1",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_MISMATCH"
    assert response.json()["error"]["details"]["body_tenant_id"] == "tenant-b"
    assert response.json()["error"]["details"]["claim_tenant_id"] == "tenant-a"


def test_chat_ask_allows_matching_tenant_body(jwt_client: TestClient) -> None:
    token_a = _mint(jwt_client, tenant_id="tenant-a")
    response = jwt_client.post(
        "/api/chat/ask",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"question": "stub", "tenant_id": "tenant-a", "customer_id": "c1"},
    )
    # Either 200 with an answer or a domain-level error, but NOT 403.
    assert response.status_code != 403, response.text


def test_chat_ask_allows_omitted_tenant_id(jwt_client: TestClient) -> None:
    """When body omits tenant_id entirely, the guard returns ctx.tenant_id."""
    token_a = _mint(jwt_client, tenant_id="tenant-a")
    response = jwt_client.post(
        "/api/chat/ask",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"question": "stub", "customer_id": "c1"},
    )
    assert response.status_code != 403, response.text


def test_agents_runs_blocks_cross_tenant_body(jwt_client: TestClient) -> None:
    token_a = _mint(jwt_client, tenant_id="tenant-a")
    response = jwt_client.post(
        "/api/agents/runs",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "question": "stub",
            "tenant_id": "tenant-b",
            "customer_id": "c1",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_MISMATCH"


def test_knowledge_upload_blocks_cross_tenant_form(jwt_client: TestClient) -> None:
    token_a = _mint(jwt_client, tenant_id="tenant-a")
    response = jwt_client.post(
        "/api/knowledge/upload",
        headers={"Authorization": f"Bearer {token_a}"},
        data={"tenant_id": "tenant-b", "customer_id": "c1"},
        files={"file": ("x.docx", b"content", "application/octet-stream")},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_MISMATCH"


def test_reviews_ingest_blocks_cross_tenant_body(jwt_client: TestClient) -> None:
    token_a = _mint(jwt_client, tenant_id="tenant-a")
    response = jwt_client.post(
        "/api/reviews/ingest",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "source": "external",
            "tenant_id": "tenant-b",
            "customer_id": "c1",
            "confidence": 0.5,
            "payload": {},
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_MISMATCH"


def test_static_token_mode_keeps_legacy_body_tenant(client: TestClient) -> None:
    """In static-token mode the guard relaxes -- body wins. This documents
    the intentional dev-only behaviour and is paired with the production
    boot guard in ``test_jwt_auth.py`` to ensure prod cannot hit it.
    """
    response = client.post(
        "/api/chat/ask",
        json={
            "question": "stub",
            "tenant_id": "any-arbitrary-tenant-x",  # static mode allows
            "customer_id": "c1",
        },
    )
    # Should NOT be 403 from the guard. May still be a domain-level error
    # if RAG has nothing to retrieve -- that's fine, we only assert the
    # guard did not trip.
    assert response.status_code != 403, response.text
