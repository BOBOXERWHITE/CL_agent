"""Lock-in tests for the P2.3 RRF fusion.

The existing ``fuse_ranked_hits`` already uses Reciprocal Rank Fusion
(``1 / (k + rank)``) rather than the hardcoded 0.65/0.35 weights the
original migration plan mentioned. These tests pin the behaviour so a
future refactor cannot silently regress to weighted-sum scoring.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.rag.retrievers import RetrievalHit, fuse_ranked_hits


def _hit(
    chunk_id: str,
    document_id: str,
    *,
    dense: float = 0.0,
    lexical: float = 0.0,
) -> RetrievalHit:
    chunk = SimpleNamespace(id=chunk_id, content="", title="", document_id=document_id)
    document = SimpleNamespace(id=document_id, filename=f"{document_id}.md", status="completed")
    return RetrievalHit(
        chunk=chunk,  # type: ignore[arg-type]
        document=document,  # type: ignore[arg-type]
        dense_score=dense,
        lexical_score=lexical,
        combined_score=max(dense, lexical),
    )


def test_rrf_fuses_rankings_from_both_channels() -> None:
    dense = [_hit("c1", "d1", dense=0.9), _hit("c2", "d2", dense=0.6)]
    lexical = [_hit("c2", "d2", lexical=0.5), _hit("c3", "d3", lexical=0.2)]

    fused = fuse_ranked_hits(dense, lexical, top_k=3, rrf_k=60, max_chunks_per_document=2)

    # c2 shows up in both channels (ranks 2 + 1) → highest RRF score
    # c1 only in dense rank 1
    # c3 only in lexical rank 2
    assert [hit.chunk_id for hit in fused[:3]] == ["c2", "c1", "c3"]


def test_rrf_score_formula_is_reciprocal_rank() -> None:
    """1 / (k + rank), verify the exact combined_score for a known input."""
    dense = [_hit("c1", "d1", dense=0.9)]  # rank 1
    lexical = [_hit("c1", "d1", lexical=0.5)]  # rank 1

    fused = fuse_ranked_hits(dense, lexical, top_k=1, rrf_k=60, max_chunks_per_document=1)
    assert len(fused) == 1
    # Two channels, both at rank 1 with k=60: score = 2 * (1 / (60 + 1))
    assert abs(fused[0].combined_score - (2 / 61)) < 1e-9


def test_rrf_respects_max_chunks_per_document() -> None:
    """Diversity rule: after fusion, cap chunks per document."""
    dense = [
        _hit("c1", "d1", dense=0.9),
        _hit("c2", "d1", dense=0.8),
        _hit("c3", "d1", dense=0.7),
        _hit("c4", "d2", dense=0.6),
    ]
    fused = fuse_ranked_hits(dense, [], top_k=4, rrf_k=60, max_chunks_per_document=2)
    doc_ids = [hit.document_id for hit in fused]
    assert doc_ids.count("d1") <= 2


def test_rrf_handles_empty_channels_gracefully() -> None:
    assert fuse_ranked_hits([], [], top_k=5, rrf_k=60, max_chunks_per_document=2) == []

    dense_only = [_hit("c1", "d1", dense=0.9)]
    fused = fuse_ranked_hits(dense_only, [], top_k=5, rrf_k=60, max_chunks_per_document=2)
    assert len(fused) == 1
    assert fused[0].chunk_id == "c1"
