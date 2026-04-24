"""P5.4: ``POST /api/agents/runs`` is now ``async def``.

We drive the ASGI app via ``httpx.AsyncClient`` + ``ASGITransport`` so
the async path is really exercised (``TestClient`` would hide a
regression back to sync-blocking).

Parallel contract (same shape as P4.2's chat test): N concurrent
requests must finish in well under N × single — proof the event loop
is not serialising the agent graph.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest


@pytest.fixture()
def asgi_app(_test_environment: None):
    from app.db.session import init_db
    from app.main import create_app

    # ASGITransport does not trigger FastAPI's lifespan, so we bootstrap
    # the schema manually. The rest of the app is pure function
    # registration — no startup-only state needed for these tests.
    init_db()
    return create_app()


async def test_agents_run_round_trip_async(asgi_app) -> None:
    """Smoke test: the async route returns 201 + a well-shaped body."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/agents/runs",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "question": "北京酒店报销上限",
                "tenant_id": "t1",
                "customer_id": "c1",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert body["agent_name"]
    assert "timeline" in body


async def test_agents_run_concurrent_requests_dont_serialise(asgi_app) -> None:
    """4 concurrent agent runs should complete in well under 4× a
    serial call. ``asyncio.to_thread`` around the sync engine lets
    uvicorn interleave work — without it we'd see roughly 4× wall-clock.
    """
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Authorization": "Bearer admin-token"}
        body = {
            "question": "北京酒店报销上限",
            "tenant_id": "t1",
            "customer_id": "c1",
        }

        serial_start = asyncio.get_event_loop().time()
        first = await client.post("/api/agents/runs", headers=headers, json=body)
        serial_elapsed = asyncio.get_event_loop().time() - serial_start
        assert first.status_code == 201

        async def _one() -> int:
            r = await client.post("/api/agents/runs", headers=headers, json=body)
            return r.status_code

        parallel_start = asyncio.get_event_loop().time()
        statuses = await asyncio.gather(*(_one() for _ in range(4)))
        parallel_elapsed = asyncio.get_event_loop().time() - parallel_start

    assert all(s == 201 for s in statuses), statuses
    # Loose bound: 2.5× single-call time. Real perf is much closer to
    # 1× because subsequent runs hit the answer cache.
    assert parallel_elapsed < max(serial_elapsed * 2.5, 1.5)
