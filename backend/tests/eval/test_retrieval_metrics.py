"""Unit tests for P2.5 retrieval IR metrics.

Pure math; no I/O. Exhaustive boundary cases so later refactors of the
benchmark runner can't silently break the metric formulas.
"""

from __future__ import annotations

import math

from app.services.eval.retrieval_metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_all_relevant_in_top_k() -> None:
    assert recall_at_k(["a", "b", "c"], {"a", "b"}, 3) == 1.0


def test_recall_at_k_partial() -> None:
    assert recall_at_k(["a", "x", "y"], {"a", "b"}, 3) == 0.5


def test_recall_at_k_top_k_truncates_retrieved() -> None:
    # Even if 'b' is in retrieved at position 5, top-3 doesn't see it.
    assert recall_at_k(["x", "y", "z", "w", "b"], {"b"}, 3) == 0.0


def test_recall_at_k_empty_relevant_returns_zero() -> None:
    assert recall_at_k(["a", "b"], set(), 3) == 0.0


def test_precision_at_k_counts_hits() -> None:
    assert precision_at_k(["a", "x", "b"], {"a", "b"}, 3) == 2 / 3


def test_precision_at_k_zero_k_returns_zero() -> None:
    assert precision_at_k(["a"], {"a"}, 0) == 0.0


def test_reciprocal_rank_first_hit() -> None:
    assert reciprocal_rank(["a", "b"], {"a"}) == 1.0


def test_reciprocal_rank_second_hit() -> None:
    assert reciprocal_rank(["x", "a", "y"], {"a"}) == 0.5


def test_reciprocal_rank_no_hit_is_zero() -> None:
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_ndcg_at_k_perfect_order() -> None:
    # Two relevant docs at ranks 1 and 2 → perfect order → nDCG = 1.
    assert ndcg_at_k(["a", "b", "x"], {"a", "b"}, 3) == 1.0


def test_ndcg_at_k_swapped_order_penalised() -> None:
    # Same two relevant docs at ranks 2 and 3 → lower than perfect.
    score = ndcg_at_k(["x", "a", "b"], {"a", "b"}, 3)
    assert 0.0 < score < 1.0


def test_ndcg_at_k_formula_matches_manual_compute() -> None:
    """Single relevant at rank 2: DCG = 1/log2(3), IDCG = 1/log2(2) = 1."""
    score = ndcg_at_k(["x", "a", "y", "z"], {"a"}, 4)
    expected = (1.0 / math.log2(3)) / 1.0
    assert abs(score - expected) < 1e-9


def test_ndcg_at_k_empty_relevant_returns_zero() -> None:
    assert ndcg_at_k(["a", "b"], set(), 5) == 0.0


def test_ndcg_at_k_no_hits_returns_zero() -> None:
    assert ndcg_at_k(["x", "y"], {"a"}, 2) == 0.0
