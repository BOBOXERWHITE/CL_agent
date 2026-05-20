"""Tests for the LEXICAL_BACKEND switch in ``retrieve_hybrid``.

The feature flag decides which lexical retriever the hybrid path calls:

  ``ilike``       → ``retrieve_lexical`` (legacy SQL ILIKE + phrase bonus)
  ``milvus_bm25`` → ``retrieve_lexical_milvus`` (Milvus 2.5 native BM25)

Both retrievers MUST return ``list[RetrievalHit]`` so the fusion +
diversity logic downstream stays unchanged. The dense path is identical
in both cases (Milvus dense ANN over the embedding field).

Unit-level: we stub the vector store and the PG-loading helper so the
test runs in microseconds and doesn't need either backend live.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.core.config import Settings, get_settings
from app.services.rag import retrievers as retrievers_mod
from app.services.rag.retrievers import (
    RetrievalHit,
    retrieve_lexical_milvus,
)


class _FakeChunk:
    def __init__(self, chunk_id: str, content: str = "", title: str = "") -> None:
        self.id = chunk_id
        self.content = content
        self.title = title


class _FakeDocument:
    def __init__(self, doc_id: str = "d1") -> None:
        self.id = doc_id
        self.filename = "policy.md"


class _FakeVectorStore:
    """Stub vector store: capture calls to search_bm25 and return canned hits."""

    def __init__(self, bm25_hits: list[tuple[str, float]] | None = None) -> None:
        self._bm25_hits = bm25_hits or []
        self.bm25_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> list[tuple[str, float]]:
        self.search_calls.append(kwargs)
        return []

    def search_bm25(self, **kwargs: Any) -> list[tuple[str, float]]:
        self.bm25_calls.append(kwargs)
        return self._bm25_hits


@pytest.fixture
def patched_vector_store(monkeypatch) -> _FakeVectorStore:
    """Replace ``get_vector_store`` with a fake; assert on the captured calls."""
    fake = _FakeVectorStore()
    monkeypatch.setattr(retrievers_mod, "get_vector_store", lambda: fake)
    return fake


@pytest.fixture
def patched_chunk_loader(monkeypatch) -> dict[str, tuple[_FakeChunk, _FakeDocument]]:
    """Replace ``_load_chunks_by_ids`` so tests don't need a real PG."""
    chunks: dict[str, tuple[_FakeChunk, _FakeDocument]] = {}

    def _fake_loader(
        tenant_id: str, customer_id: str, chunk_ids: list[str]
    ) -> list[tuple[_FakeChunk, _FakeDocument]]:
        del tenant_id, customer_id
        return [chunks[cid] for cid in chunk_ids if cid in chunks]

    monkeypatch.setattr(retrievers_mod, "_load_chunks_by_ids", _fake_loader)
    return chunks


def _override_lexical_backend(monkeypatch, value: str) -> Settings:
    settings = get_settings()
    overridden = replace(settings, lexical_backend=value)
    monkeypatch.setattr(retrievers_mod, "get_settings", lambda: overridden)
    return overridden


# ---------------------------------------------------------------------------
# retrieve_lexical_milvus
# ---------------------------------------------------------------------------


def test_retrieve_lexical_milvus_returns_empty_when_vector_store_returns_nothing(
    patched_vector_store: _FakeVectorStore,
) -> None:
    hits = retrieve_lexical_milvus(
        question="北京酒店", tenant_id="t1", customer_id="cust1", top_k=5
    )
    assert hits == []
    # The call MUST have been forwarded to search_bm25, not search.
    assert len(patched_vector_store.bm25_calls) == 1
    assert patched_vector_store.bm25_calls[0]["query_text"] == "北京酒店"
    assert patched_vector_store.bm25_calls[0]["top_k"] >= 5
    assert patched_vector_store.search_calls == []


def test_retrieve_lexical_milvus_maps_bm25_scores_to_lexical_score(
    monkeypatch,
    patched_chunk_loader: dict[str, tuple[_FakeChunk, _FakeDocument]],
) -> None:
    """The BM25 scalar from Milvus must land in the ``lexical_score`` slot
    so RRF fusion treats it the same as the legacy ILIKE score."""
    patched_chunk_loader["c1"] = (_FakeChunk("c1", content="北京酒店内容"), _FakeDocument("d1"))
    patched_chunk_loader["c2"] = (_FakeChunk("c2", content="其他内容"), _FakeDocument("d2"))

    fake = _FakeVectorStore(bm25_hits=[("c1", 2.34), ("c2", 1.11)])
    monkeypatch.setattr(retrievers_mod, "get_vector_store", lambda: fake)

    hits = retrieve_lexical_milvus(
        question="北京酒店", tenant_id="t1", customer_id="cust1", top_k=5
    )

    assert [h.chunk_id for h in hits] == ["c1", "c2"]
    assert all(isinstance(h, RetrievalHit) for h in hits)
    assert hits[0].lexical_score == pytest.approx(2.34)
    assert hits[0].dense_score == 0.0
    assert hits[0].combined_score == pytest.approx(2.34)
    assert hits[1].lexical_score == pytest.approx(1.11)


def test_retrieve_lexical_milvus_drops_chunks_missing_from_pg(
    monkeypatch,
    patched_chunk_loader: dict[str, tuple[_FakeChunk, _FakeDocument]],
) -> None:
    """Milvus may return a chunk_id that no longer exists in PG (e.g. a
    document was deleted but the Milvus row hasn't been GC'd yet). The
    retriever must drop those silently instead of crashing."""
    patched_chunk_loader["c1"] = (_FakeChunk("c1"), _FakeDocument("d1"))
    fake = _FakeVectorStore(bm25_hits=[("c1", 2.0), ("c_ghost", 1.0)])
    monkeypatch.setattr(retrievers_mod, "get_vector_store", lambda: fake)

    hits = retrieve_lexical_milvus(question="q", tenant_id="t1", customer_id="cust1", top_k=5)
    assert [h.chunk_id for h in hits] == ["c1"]


# ---------------------------------------------------------------------------
# retrieve_hybrid backend switch
# ---------------------------------------------------------------------------


def test_retrieve_hybrid_default_backend_uses_ilike_path(monkeypatch) -> None:
    """Default LEXICAL_BACKEND=ilike: legacy retrieve_lexical is called,
    Milvus search_bm25 is NOT touched. Pins backward compatibility."""
    _override_lexical_backend(monkeypatch, "ilike")
    dense_called: list[int] = []
    ilike_called: list[int] = []
    milvus_lex_called: list[int] = []

    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_dense",
        lambda question, tenant_id, customer_id, top_k: (dense_called.append(1) or []),
    )
    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_lexical",
        lambda question, tenant_id, customer_id, top_k: (ilike_called.append(1) or []),
    )
    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_lexical_milvus",
        lambda question, tenant_id, customer_id, top_k: (milvus_lex_called.append(1) or []),
    )

    retrievers_mod.retrieve_hybrid("q", "t1", "cust1", top_k=5)

    assert dense_called == [1]
    assert ilike_called == [1]
    assert milvus_lex_called == []


def test_retrieve_hybrid_milvus_bm25_backend_uses_milvus_lex(monkeypatch) -> None:
    _override_lexical_backend(monkeypatch, "milvus_bm25")
    dense_called: list[int] = []
    ilike_called: list[int] = []
    milvus_lex_called: list[int] = []

    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_dense",
        lambda question, tenant_id, customer_id, top_k: (dense_called.append(1) or []),
    )
    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_lexical",
        lambda question, tenant_id, customer_id, top_k: (ilike_called.append(1) or []),
    )
    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_lexical_milvus",
        lambda question, tenant_id, customer_id, top_k: (milvus_lex_called.append(1) or []),
    )

    retrievers_mod.retrieve_hybrid("q", "t1", "cust1", top_k=5)

    assert dense_called == [1]
    assert ilike_called == []
    assert milvus_lex_called == [1]


def test_retrieve_hybrid_unknown_backend_falls_back_to_ilike(monkeypatch) -> None:
    """Defensive: a typo in env var must not silently dark-launch BM25.
    Unknown value falls back to the legacy ILIKE path with a warning."""
    _override_lexical_backend(monkeypatch, "made_up_value")
    ilike_called: list[int] = []
    milvus_lex_called: list[int] = []
    monkeypatch.setattr(retrievers_mod, "retrieve_dense", lambda *a, **kw: [])
    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_lexical",
        lambda question, tenant_id, customer_id, top_k: (ilike_called.append(1) or []),
    )
    monkeypatch.setattr(
        retrievers_mod,
        "retrieve_lexical_milvus",
        lambda question, tenant_id, customer_id, top_k: (milvus_lex_called.append(1) or []),
    )

    retrievers_mod.retrieve_hybrid("q", "t1", "cust1", top_k=5)
    assert ilike_called == [1]
    assert milvus_lex_called == []
