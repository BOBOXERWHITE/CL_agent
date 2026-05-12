"""Standard IR metrics for retrieval evaluation.

- recall@k:        |retrieved_top_k ∩ relevant| / |relevant|
- precision@k:     |retrieved_top_k ∩ relevant| / k
- MRR:             1 / rank_of_first_relevant_hit  (or 0 if none)
- nDCG@k:          DCG@k / IDCG@k, binary relevance
- context_precision (RAGAS-style): weighted P@k, rewards relevant
                   chunks at low ranks. Input is a list of per-rank
                   relevance booleans.
- context_recall:  fraction of expected atomic facts that appear in
                   the union of retrieved chunks. Input is chunk text +
                   expected substring keywords.

All inputs are simple lists / strings; pure functions, no I/O. The
runner.py module composes these with per-sample relevance signals
(keyword-match or LLM-judge) to produce dataset-level aggregates.
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


def context_precision(relevance_marks: list[bool], k: int | None = None) -> float:
    """RAGAS-aligned context_precision.

    Weighted precision that rewards retrieval systems for placing
    relevant chunks at low ranks:

        context_precision = ( Σ_{k=1..K} P@k · v_k ) / max(Σ v_k, 1)

    where ``v_k`` is 1 if the rank-k chunk is relevant, 0 otherwise.
    With a single relevant chunk this collapses to ``1 / rank``;
    with multiple relevant chunks it averages the P@k at each hit.

    Returns 0.0 for an empty input or zero relevant chunks — both
    indistinguishable from "retrieval told us nothing useful". Pass
    ``k`` to cap evaluation at the first ``k`` ranks (RAGAS default
    is "all retrieved chunks"; capping is useful when you want a
    metric that ignores deep-rank serendipity).
    """
    if k is not None and k <= 0:
        return 0.0
    truncated = relevance_marks if k is None else relevance_marks[:k]
    if not truncated:
        return 0.0
    relevant_seen = 0
    precision_sum_at_hits = 0.0
    for rank, is_relevant in enumerate(truncated, start=1):
        if is_relevant:
            relevant_seen += 1
            precision_sum_at_hits += relevant_seen / rank
    if relevant_seen == 0:
        return 0.0
    return precision_sum_at_hits / relevant_seen


def context_recall(chunks: list[str], expected_keywords: list[str]) -> float:
    """Fraction of expected atomic facts covered by retrieved chunks.

    Each entry in ``expected_keywords`` represents one atomic fact the
    gold answer relies on. Recall = (atoms found in the union of chunks)
    / (total expected atoms). Case-insensitive substring match because
    expected_keywords already encodes the canonical form of each fact;
    forcing strict casing would surface noise from ``"Shanghai"`` vs.
    ``"shanghai"`` mismatches rather than real recall problems.

    Conventions:
      - Empty ``expected_keywords`` → ``1.0`` (vacuously recalled; lets
        runner aggregations stay simple without per-sample guards).
      - Empty ``chunks``           → ``0.0`` (nothing retrieved).
    """
    if not expected_keywords:
        return 1.0
    if not chunks:
        return 0.0
    haystack = "\n".join(chunks).lower()
    hits = sum(1 for kw in expected_keywords if kw.strip().lower() in haystack)
    return hits / len(expected_keywords)


__all__ = [
    "context_precision",
    "context_recall",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
