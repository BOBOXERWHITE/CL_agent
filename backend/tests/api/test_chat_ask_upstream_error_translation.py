"""Pins the contract: upstream LLM 4xx/5xx never surfaces as a bare 500.

Background (the bug this fix closes)
====================================

Before this change ``ask_policy_question`` let ``httpx.HTTPStatusError``
from the upstream LLM gateway propagate all the way to the FastAPI
default exception handler, which turned it into ``500 Internal Server
Error`` with no body. The frontend then displayed "服务器出错"; operators
opened the backend code looking for a backend bug; the real cause was
upstream rate limiting / quota exhaustion (Volces ARK 429, OpenAI 429,
DashScope 429 — all common).

This file pins the new behaviour so a future refactor can't silently
regress it:

  upstream 4xx / 5xx     → HTTP 503 + JSON body with upstream status,
                           upstream body[:500], and an actionable hint
  upstream unreachable   → HTTP 504 + JSON body with exception type
  (network / timeout)      and message
  any other path         → unchanged

The tests stub ``answer_policy_question_async`` directly so they don't
need a live LLM and don't accidentally hit the real ARK gateway.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture()
def asgi_app(_test_environment: None) -> object:
    """Build a fresh FastAPI app bound to the per-test SQLite DB."""
    from app.main import create_app

    return create_app()


def _fake_429_response() -> httpx.Response:
    """A response object that mimics a real ARK 429 — the body matters
    because the route forwards it to the frontend for triage."""
    request = httpx.Request("POST", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    return httpx.Response(
        429,
        request=request,
        content=(
            b'{"error":{"code":"RateLimit","message":"You exceeded the QPM limit",'
            b'"type":"requests","request_id":"abc123"}}'
        ),
    )


def _fake_401_response() -> httpx.Response:
    request = httpx.Request("POST", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    return httpx.Response(
        401,
        request=request,
        content=b'{"error":{"code":"InvalidApiKey","message":"key expired"}}',
    )


async def test_upstream_429_returns_503_with_upstream_body(
    asgi_app, seeded_policy_chunks: None, monkeypatch
) -> None:
    response_obj = _fake_429_response()
    err = httpx.HTTPStatusError("429", request=response_obj.request, response=response_obj)

    async def _raise_429(**_kwargs: object) -> object:
        raise err

    monkeypatch.setattr(
        "app.api.routes.chat.answer_policy_question_async",
        _raise_429,
    )

    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/chat/ask",
            headers={"Authorization": "Bearer admin-token"},
            json={"question": "Q", "tenant_id": "t1", "customer_id": "c1"},
        )

    assert resp.status_code == 503, resp.text
    body = resp.json()
    # ``app.api.error_handlers.http_exception_handler`` reformats every
    # HTTPException(detail=dict) into the project's unified envelope:
    #   { "error": { "code", "message", "request_id", "details": {...} },
    #     "detail": "" }
    # The fields we set in chat.py land under ``error.details``.
    details = body["error"]["details"]
    assert details["error"] == "llm_upstream_error"
    assert details["upstream_status"] == 429
    assert "QPM" in details["upstream_body"]
    assert "RateLimit" in details["upstream_body"]
    assert "rate limit" in details["hint"].lower()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"


async def test_upstream_401_returns_503_with_invalid_key_body(
    asgi_app, seeded_policy_chunks: None, monkeypatch
) -> None:
    """Same translation works for 401 (invalid / revoked key) — the
    point of the body forward is letting ops distinguish the failure
    modes from the HTTP 503 alone."""
    response_obj = _fake_401_response()
    err = httpx.HTTPStatusError("401", request=response_obj.request, response=response_obj)

    async def _raise_401(**_kwargs: object) -> object:
        raise err

    monkeypatch.setattr(
        "app.api.routes.chat.answer_policy_question_async",
        _raise_401,
    )

    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/chat/ask",
            headers={"Authorization": "Bearer admin-token"},
            json={"question": "Q", "tenant_id": "t1", "customer_id": "c1"},
        )

    assert resp.status_code == 503
    details = resp.json()["error"]["details"]
    assert details["upstream_status"] == 401
    assert "InvalidApiKey" in details["upstream_body"]


async def test_upstream_unreachable_returns_504(
    asgi_app, seeded_policy_chunks: None, monkeypatch
) -> None:
    """Connection refused / DNS failure / timeout = upstream unreachable
    = HTTP 504 (gateway timeout). Distinct from 503 (gateway received
    an error) so dashboards can chart the two failure modes apart."""

    async def _raise_connect(**_kwargs: object) -> object:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(
        "app.api.routes.chat.answer_policy_question_async",
        _raise_connect,
    )

    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/chat/ask",
            headers={"Authorization": "Bearer admin-token"},
            json={"question": "Q", "tenant_id": "t1", "customer_id": "c1"},
        )

    assert resp.status_code == 504
    body = resp.json()
    details = body["error"]["details"]
    assert details["error"] == "llm_upstream_unreachable"
    assert details["exception_type"] == "ConnectError"
    # The unified envelope's http_exception_handler promotes detail.get("message")
    # to the top-level ``error.message`` field and strips it from details.
    assert "refused" in body["error"]["message"].lower()
