"""Tests for the unified exception handler stack.

Covers:
- Domain ``AppException`` → structured body with ``error_code`` and
  ``request_id``.
- Pydantic ``RequestValidationError`` → 422 with field-level details.
- Legacy ``HTTPException`` raises → same unified body (backward compat).
- Uncaught ``Exception`` → 500 with sanitized message.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.error_handlers import register_error_handlers
from app.core.errors import BadRequest, NotFound, UpstreamError
from app.schemas.errors import ErrorResponse


def _make_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise-not-found")
    def raise_not_found() -> None:
        raise NotFound("widget missing", error_code="WIDGET_NOT_FOUND")

    @app.get("/raise-bad-request")
    def raise_bad_request() -> None:
        raise BadRequest(
            "amount required",
            error_code="AMOUNT_REQUIRED",
            details={"field": "amount"},
        )

    @app.get("/raise-upstream")
    def raise_upstream() -> None:
        raise UpstreamError("vector store timed out")

    @app.get("/raise-http")
    def raise_http() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="duplicate key")

    @app.get("/raise-random")
    def raise_random() -> None:
        raise RuntimeError("unexpected explosion")

    return app


def test_app_exception_returns_structured_body() -> None:
    client = TestClient(_make_app())
    response = client.get("/raise-not-found")
    assert response.status_code == 404
    body = response.json()
    # New structured format.
    assert body["error"]["code"] == "WIDGET_NOT_FOUND"
    assert body["error"]["message"] == "widget missing"
    assert "request_id" in body["error"]
    # Legacy shim for existing clients.
    assert body["detail"] == "widget missing"
    # Validated shape via Pydantic.
    ErrorResponse.model_validate(body)


def test_app_exception_passes_details() -> None:
    client = TestClient(_make_app())
    response = client.get("/raise-bad-request")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "AMOUNT_REQUIRED"
    assert body["error"]["details"] == {"field": "amount"}


def test_upstream_error_maps_to_502() -> None:
    client = TestClient(_make_app())
    response = client.get("/raise-upstream")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_ERROR"


def test_legacy_http_exception_reformatted_to_same_envelope() -> None:
    client = TestClient(_make_app())
    response = client.get("/raise-http")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["message"] == "duplicate key"
    assert body["detail"] == "duplicate key"


def test_uncaught_exception_returns_500_with_sanitized_message() -> None:
    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/raise-random")
    assert response.status_code == 500
    body = response.json()
    # Must not leak internal exception message.
    assert "unexpected explosion" not in body["error"]["message"]
    assert body["error"]["code"] == "INTERNAL_ERROR"


def test_request_validation_error_returns_422_with_fields() -> None:
    app = FastAPI()
    register_error_handlers(app)

    from pydantic import BaseModel

    class Payload(BaseModel):
        name: str
        age: int

    @app.post("/validate")
    def validate(payload: Payload) -> dict[str, str]:
        return {"name": payload.name}

    client = TestClient(app)
    response = client.post("/validate", json={"name": "ok"})  # missing age
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "fields" in body["error"]["details"]
