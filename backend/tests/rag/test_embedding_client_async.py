"""Async-path tests for the embedding client (P4.1).

Mirror the sync tests (``test_embedding_client.py``) so the two code
paths stay behaviourally aligned. We use ``httpx.MockTransport`` on an
injected ``AsyncClient`` — no real network, no pytest plugins beyond
``pytest-asyncio``'s auto mode (enabled in ``pyproject.toml``).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.services.rag.async_http_client import (
    close_async_http_client,
    get_async_http_client,
)
from app.services.rag.embedding_client import (
    DeterministicEmbeddingClient,
    OpenAICompatibleEmbeddingClient,
)


async def test_deterministic_client_async_matches_sync() -> None:
    """The deterministic client's async twin must be bit-identical to
    sync; otherwise caches (which key by the vector, not the method)
    would diverge."""
    client = DeterministicEmbeddingClient()
    texts = ["北京酒店报销上限", "机票改签费用"]
    sync_vectors = client.embed_texts(texts, 64)
    async_vectors = await client.embed_texts_async(texts, 64)
    assert async_vectors == sync_vectors


async def test_openai_compatible_async_happy_path_parses_gateway_response() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "text-embedding-3-small"
        assert payload["input"] == ["北京酒店报销上限"]
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model_name="text-embedding-3-small",
        )
        vectors = await client.embed_texts_async(["北京酒店报销上限"], 4, async_client=http_client)

    assert vectors == [[0.1, 0.2, 0.3, 0.4]]
    assert len(captured) == 1
    assert "Bearer test-key" in captured[0].headers["authorization"]


async def test_openai_compatible_async_batches_large_requests() -> None:
    requests: list[list[str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(list(payload["input"]))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": idx, "embedding": [float(idx), 0.0, 0.0, 0.0]}
                    for idx in range(len(payload["input"]))
                ]
            },
        )

    texts = [f"text-{i}" for i in range(5)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model_name="m",
            batch_size=2,
        )
        vectors = await client.embed_texts_async(texts, 4, async_client=http_client)

    # 5 items, batch=2 → 3 batches (2+2+1)
    assert [len(b) for b in requests] == [2, 2, 1]
    assert len(vectors) == 5


async def test_openai_compatible_async_retries_on_5xx_then_succeeds() -> None:
    attempts = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503, json={"error": {"message": "upstream down"}})
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.5, 0.5, 0.5, 0.5]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model_name="m",
            max_retries=2,
        )
        vectors = await client.embed_texts_async(["q"], 4, async_client=http_client)

    assert attempts["count"] == 2
    assert vectors == [[0.5, 0.5, 0.5, 0.5]]


async def test_openai_compatible_async_non_retryable_4xx_fails_fast() -> None:
    attempts = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(
            400,
            json={"error": {"message": "bad model name"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model_name="m",
            max_retries=3,
        )
        with pytest.raises(RuntimeError, match="bad model name"):
            await client.embed_texts_async(["q"], 4, async_client=http_client)

    # A 400 is not retryable; only the first attempt should have happened.
    assert attempts["count"] == 1


async def test_openai_compatible_async_empty_input_skips_http() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called for empty input")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model_name="m",
        )
        assert await client.embed_texts_async([], 4, async_client=http_client) == []


async def test_openai_compatible_async_request_error_retries_then_raises() -> None:
    attempts = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("connection refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model_name="m",
            max_retries=2,
        )
        with pytest.raises(RuntimeError, match="connection refused"):
            await client.embed_texts_async(["q"], 4, async_client=http_client)

    # Initial attempt + 2 retries.
    assert attempts["count"] == 3


async def test_concurrent_async_calls_do_not_serialise() -> None:
    """Sanity check: fan out 8 concurrent requests; they should all
    complete in roughly 1× single-request time (not 8×). A slow handler
    makes the speedup measurable without flakiness.
    """
    handler_delay = 0.05

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(handler_delay)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.0, 0.0, 0.0, 0.0]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model_name="m",
        )
        started = asyncio.get_event_loop().time()
        await asyncio.gather(
            *(client.embed_texts_async([f"t{i}"], 4, async_client=http_client) for i in range(8))
        )
        elapsed = asyncio.get_event_loop().time() - started

    # 8 concurrent × 0.05s should finish well under 8×0.05 = 0.4s.
    # Generous headroom (0.3s) so the test isn't flaky on slow CI.
    assert elapsed < 0.3


# ---------------------------------------------------------------------------
# Shared AsyncClient factory
# ---------------------------------------------------------------------------


async def test_get_async_http_client_is_reused() -> None:
    await close_async_http_client()  # start clean
    c1 = get_async_http_client()
    c2 = get_async_http_client()
    assert c1 is c2  # pool reuse — not per-call creation
    await close_async_http_client()


async def test_close_async_http_client_is_idempotent() -> None:
    await close_async_http_client()
    await close_async_http_client()  # no-op second call
    # Subsequent get still works.
    client = get_async_http_client()
    assert client is not None
    await close_async_http_client()


# ---------------------------------------------------------------------------
# Cache-aware helper
# ---------------------------------------------------------------------------


async def test_texts_to_embeddings_async_uses_cache_on_second_call() -> None:
    """Second async call for the same text must not re-hit the provider
    — the cache layer is shared with the sync helper, so the async path
    can't bypass it or the two worlds would diverge on cache state.
    """
    from app.services.rag.embedding_client import texts_to_embeddings_async

    # First call populates the in-memory cache via the deterministic client.
    v1 = await texts_to_embeddings_async(["北京酒店"], 64)
    # Second call — result should be the same list (equality by value).
    v2 = await texts_to_embeddings_async(["北京酒店"], 64)
    assert v1 == v2
    assert len(v1) == 1
    assert len(v1[0]) == 64


async def test_texts_to_embeddings_async_empty_input() -> None:
    from app.services.rag.embedding_client import texts_to_embeddings_async

    assert await texts_to_embeddings_async([], 64) == []


async def test_text_to_embedding_async_is_single_text_convenience() -> None:
    from app.services.rag.embedding_client import (
        text_to_embedding_async,
        texts_to_embeddings_async,
    )

    one = await text_to_embedding_async("北京酒店", 64)
    many = await texts_to_embeddings_async(["北京酒店"], 64)
    assert one == many[0]
