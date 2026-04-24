"""Route-level async test for P4.2.

The existing chat tests use ``TestClient`` (sync wrapper), which hides
whether our route is actually coroutine-driven. This test drives the
ASGI app via ``httpx.AsyncClient`` + ``ASGITransport`` so we exercise
the real async path end-to-end.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest


@pytest.fixture()
def asgi_app(_test_environment: None) -> object:
    """Build a fresh FastAPI app bound to the per-test SQLite DB."""
    from app.main import create_app

    return create_app()


async def test_chat_ask_async_round_trip(asgi_app, seeded_policy_chunks: None) -> None:
    """End-to-end: ``POST /api/chat/ask`` served by the async route
    returns a well-formed payload. Guards against an accidentally
    missing ``await`` in the async chain.
    """
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/chat/ask",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "question": "北京酒店报销上限",
                "tenant_id": "t1",
                "customer_id": "c1",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"]
    assert "confidence" in body
    assert "retrieval_trace" in body


async def test_chat_ask_concurrent_requests_complete(asgi_app, seeded_policy_chunks: None) -> None:
    """Fire 4 concurrent chat requests. They must all succeed;
    additionally the total wall-clock must be less than 4× a serial
    call — if the route is still secretly sync-blocking, we'd hit
    roughly 4× (a test that sometimes flaked on shared runners but
    caught the regression when it mattered). Loose bound: 2.5× upper.
    """
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Authorization": "Bearer admin-token"}

        serial_start = asyncio.get_event_loop().time()
        serial_resp = await client.post(
            "/api/chat/ask",
            headers=headers,
            json={"question": "北京酒店", "tenant_id": "t1", "customer_id": "c1"},
        )
        serial_elapsed = asyncio.get_event_loop().time() - serial_start
        assert serial_resp.status_code == 200

        async def _one() -> int:
            r = await client.post(
                "/api/chat/ask",
                headers=headers,
                json={
                    "question": "北京酒店",
                    "tenant_id": "t1",
                    "customer_id": "c1",
                },
            )
            return r.status_code

        parallel_start = asyncio.get_event_loop().time()
        statuses = await asyncio.gather(*(_one() for _ in range(4)))
        parallel_elapsed = asyncio.get_event_loop().time() - parallel_start

    assert all(s == 200 for s in statuses), statuses
    # 4 concurrent requests must not balloon to ~4× single-request time.
    # The second-onwards requests hit the answer cache so they're near-free
    # — we just want to confirm the event loop isn't serialised.
    assert parallel_elapsed < max(serial_elapsed * 2.5, 1.0)
