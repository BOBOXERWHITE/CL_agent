"""Tests for the P1.2 RequestContext extension.

Verifies that ``get_request_context`` populates tenant_id / user_id / role /
roles from the verified Bearer claim, not from the request body or headers.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import RequestContext, get_request_context


@pytest.fixture()
def jwt_app(_test_environment: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JWT_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-signing-key-please-change-me")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ISSUER", "travel-ops-copilot")
    monkeypatch.setenv("JWT_AUDIENCE", "travel-ops-copilot-api")
    monkeypatch.setenv("JWT_DEV_TOKEN_ENDPOINT_ENABLED", "true")

    from app.core.config import get_settings

    get_settings.cache_clear()

    app = FastAPI()
    from app.api.error_handlers import register_error_handlers
    from app.api.routes.auth import router as auth_router

    register_error_handlers(app)
    app.include_router(auth_router)

    @app.get("/who-am-i")
    def who_am_i(ctx: RequestContext = Depends(get_request_context)) -> dict[str, object]:
        return {
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "role": ctx.role,
            "roles": list(ctx.roles),
            "request_id": ctx.request_id,
        }

    with TestClient(app) as client:
        yield client

    get_settings.cache_clear()


def _mint(client: TestClient, **kwargs: object) -> str:
    body: dict[str, object] = {
        "user_id": kwargs.get("user_id", "alice"),
        "tenant_id": kwargs.get("tenant_id", "tenant-alpha"),
        "roles": list(kwargs.get("roles", ("operator",))),  # type: ignore[arg-type]
    }
    response = client.post("/api/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_request_context_populated_from_jwt_claim(jwt_app: TestClient) -> None:
    token = _mint(jwt_app, user_id="bob", tenant_id="tenant-zeta", roles=("operator", "reviewer"))
    response = jwt_app.get("/who-am-i", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-zeta"
    assert body["user_id"] == "bob"
    assert set(body["roles"]) == {"operator", "reviewer"}
    assert body["role"] in {"operator", "reviewer"}  # primary role from precedence
    assert body["request_id"]


def test_request_context_ignores_attempted_body_tenant_override(jwt_app: TestClient) -> None:
    # The endpoint above has no body, but this test asserts the claim wins
    # over headers that previously could have leaked into request.state.
    token = _mint(jwt_app, tenant_id="tenant-alpha")
    response = jwt_app.get(
        "/who-am-i",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-Override": "tenant-evil",  # nothing reads this; sanity check
        },
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-alpha"


def test_request_context_uses_supplied_request_id(jwt_app: TestClient) -> None:
    token = _mint(jwt_app)
    response = jwt_app.get(
        "/who-am-i",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-ID": "trace-abc-123",
        },
    )
    assert response.status_code == 200
    assert response.json()["request_id"] == "trace-abc-123"


def test_request_context_static_token_mode_uses_default_tenant(client: TestClient) -> None:
    """In static-token mode (jwt_enabled=false), tenant_id falls back to the
    well-known dev default since static tokens carry no claim. Verifies the
    legacy compatibility path keeps working until tests migrate.
    """

    # The default ``client`` fixture sends Authorization: Bearer admin-token.
    # We need an endpoint that exposes RequestContext for inspection -- the
    # built-in routes do not return the context body, so use a tiny add-on app.
    from app.api.error_handlers import register_error_handlers

    helper = FastAPI()
    register_error_handlers(helper)

    @helper.get("/inspect")
    def inspect(ctx: RequestContext = Depends(get_request_context)) -> dict[str, object]:
        return {"tenant_id": ctx.tenant_id, "role": ctx.role, "user_id": ctx.user_id}

    with TestClient(helper) as helper_client:
        response = helper_client.get("/inspect", headers={"Authorization": "Bearer admin-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "default-tenant"
    assert body["role"] == "admin"
    assert body["user_id"] == "static-admin"
