"""Standard IR metrics for retrieval evaluation.

- recall@k:   |retrieved_top_k ∩ relevant| / |relevant|
- precision@k: |retrieved_top_k ∩ relevant| / k
- MRR:        1 / rank_of_first_relevant_hit  (or 0 if none)
- nDCG@k:     DCG@k / IDCG@k, binary relevance

All inputs are ordered lists of chunk_ids; ``relevant`` is a set.
Pure functions, no I/O -- suitable for unit testing without fixtures.
"""

from __future__ import annotations

import math


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    hits = len(top_k & relevant)
    return hits / len(relevant)


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for chunk_id in top_k if chunk_id in relevant)
    return hits / len(top_k)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG@k.

    DCG@k = Σ rel_i / log2(i + 1), for i in 1..k
    IDCG@k is the DCG if every top slot were a relevant doc, capped at |relevant|.
    """
    if not relevant or k <= 0:
        return 0.0
    dcg = 0.0
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in relevant:
            dcg += 1.0 / math.log2(rank + 1)

    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    if idcg == 0:
        return 0.0
    return dcg / idcg


__all__ = ["ndcg_at_k", "precision_at_k", "recall_at_k", "reciprocal_rank"]
