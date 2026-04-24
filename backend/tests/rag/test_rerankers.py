"""Tests for the P2.4 reranker provider abstraction.

Covers:
- Default heuristic path still works and keeps legacy scoring behaviour.
- OpenAI-compatible path posts to /rerank and respects the upstream ordering.
- OpenAI-compatible path downgrades to heuristic on HTTP error / malformed body.
- OpenAI-compatible path requires (base_url, api_key, model_name); missing any
  falls back to heuristic with a warning.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.rag.rerankers import (
    OpenAICompatibleRerankerClient,
    rerank_hits,
)
from app.services.rag.retrievers import RetrievalHit


def _hit(chunk_id: str, content: str, *, combined: float = 0.0) -> RetrievalHit:
    chunk = SimpleNamespace(id=chunk_id, content=content, title="", document_id=f"d-{chunk_id}")
    document = SimpleNamespace(id=f"d-{chunk_id}", filename=f"{chunk_id}.md", status="completed")
    return RetrievalHit(
        chunk=chunk,  # type: ignore[arg-type]
        document=document,  # type: ignore[arg-type]
        dense_score=0.0,
        lexical_score=0.0,
        combined_score=combined,
    )


def test_heuristic_rerank_applies_phrase_bonus(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default env: RERANKER_PROVIDER=heuristic
    from app.core.config import get_settings

    get_settings.cache_clear()

    hits = [
        _hit("a", "unrelated content", combined=0.5),
        _hit("b", "this mentions 北京酒店 directly", combined=0.3),
    ]
    reranked = rerank_hits("北京酒店", hits, top_k=2)
    # b's phrase bonus should surface it above a
    assert reranked[0].chunk_id == "b"


def test_openai_compatible_rerank_respects_upstream_ordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rerank")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["query"] == "testing"
        assert payload["documents"] == ["first doc", "second doc", "third doc"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.60},
                    {"index": 1, "relevance_score": 0.30},
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleRerankerClient(
        base_url="https://rerank.example.com/v1",
        api_key="test-key",
        model_name="rerank-v1",
        timeout_seconds=5.0,
        http_client=http_client,
    )

    hits = [
        _hit("a", "first doc"),
        _hit("b", "second doc"),
        _hit("c", "third doc"),
    ]
    reranked = client.rerank("testing", hits, top_k=3)
    assert [h.chunk_id for h in reranked] == ["c", "a", "b"]
    assert reranked[0].combined_score == 0.95


def test_openai_compatible_rerank_http_error_falls_back_to_heuristic() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream exploded"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleRerankerClient(
        base_url="https://rerank.example.com/v1",
        api_key="test-key",
        model_name="rerank-v1",
        timeout_seconds=5.0,
        http_client=http_client,
    )
    hits = [_hit("a", "北京酒店 mention", combined=0.1)]
    # Should not raise -- falls back to heuristic.
    reranked = client.rerank("北京酒店", hits, top_k=1)
    assert len(reranked) == 1
    assert reranked[0].chunk_id == "a"


def test_openai_compatible_rerank_malformed_body_falls_back() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleRerankerClient(
        base_url="https://rerank.example.com/v1",
        api_key="test-key",
        model_name="rerank-v1",
        timeout_seconds=5.0,
        http_client=http_client,
    )
    hits = [_hit("a", "doc-a"), _hit("b", "doc-b")]
    reranked = client.rerank("anything", hits, top_k=2)
    # Fallback preserves hits; we just care it didn't raise.
    assert len(reranked) == 2


def test_rerank_hits_falls_back_when_config_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """openai-compatible without base_url / api_key / model → heuristic."""
    monkeypatch.setenv("RERANKER_PROVIDER", "openai-compatible")
    monkeypatch.setenv("RERANKER_API_BASE_URL", "")  # missing
    monkeypatch.setenv("RERANKER_API_KEY", "k")
    monkeypatch.setenv("RERANKER_MODEL_NAME", "m")
    from app.core.config import get_settings

    get_settings.cache_clear()

    hits = [_hit("a", "北京酒店", combined=0.2)]
    reranked = rerank_hits("北京酒店", hits, top_k=1)
    # Heuristic path; phrase bonus lifts the score.
    assert reranked[0].combined_score > 0.2
    get_settings.cache_clear()
