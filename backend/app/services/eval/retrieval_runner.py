"""Retrieval quality evaluation: run a labelled benchmark, emit metrics.

A benchmark is a list of ``RetrievalSample``::

    {
        "query": "北京酒店报销上限",
        "tenant_id": "t1",
        "customer_id": "c1",
        "relevant_chunk_ids": ["chunk-uuid-1", "chunk-uuid-3"],
    }

The runner drives ``retrieve_hybrid`` for each sample, records top-k chunk
ids, and aggregates recall@5 / recall@10 / precision@5 / nDCG@10 / MRR.

This is the operator-facing lever for P2.5: a concrete number you can
compare before and after any retrieval change (new embedding model,
tweaked RRF k, new reranker, query rewriter upgrade, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from app.services.eval.retrieval_metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.services.rag.retrievers import retrieve_hybrid


@dataclass(frozen=True)
class RetrievalSample:
    query: str
    tenant_id: str
    customer_id: str
    relevant_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class PerSampleResult:
    query: str
    retrieved_chunk_ids: tuple[str, ...]
    relevant_chunk_ids: tuple[str, ...]
    recall_at_5: float
    recall_at_10: float
    precision_at_5: float
    ndcg_at_10: float
    reciprocal_rank: float
    latency_ms: float


@dataclass(frozen=True)
class RetrievalEvalReport:
    sample_count: int
    metrics: dict[str, float]
    per_sample: list[PerSampleResult] = field(default_factory=list)


def _evaluate_sample(sample: RetrievalSample, retrieve_top_k: int) -> PerSampleResult:
    started = perf_counter()
    hits = retrieve_hybrid(
        sample.query,
        sample.tenant_id,
        sample.customer_id,
        retrieve_top_k,
    )
    latency_ms = (perf_counter() - started) * 1000

    retrieved_ids = [hit.chunk_id for hit in hits]
    relevant = set(sample.relevant_chunk_ids)
    return PerSampleResult(
        query=sample.query,
        retrieved_chunk_ids=tuple(retrieved_ids),
        relevant_chunk_ids=sample.relevant_chunk_ids,
        recall_at_5=recall_at_k(retrieved_ids, relevant, 5),
        recall_at_10=recall_at_k(retrieved_ids, relevant, 10),
        precision_at_5=precision_at_k(retrieved_ids, relevant, 5),
        ndcg_at_10=ndcg_at_k(retrieved_ids, relevant, 10),
        reciprocal_rank=reciprocal_rank(retrieved_ids, relevant),
        latency_ms=round(latency_ms, 2),
    )


def run_retrieval_eval(
    samples: list[RetrievalSample], *, retrieve_top_k: int = 10
) -> RetrievalEvalReport:
    """Evaluate ``samples`` and aggregate metrics.

    Empty input returns zeros (not an error) so callers can treat
    "no benchmark loaded" as a neutral state.
    """
    if not samples:
        return RetrievalEvalReport(
            sample_count=0,
            metrics={
                "recall_at_5": 0.0,
                "recall_at_10": 0.0,
                "precision_at_5": 0.0,
                "ndcg_at_10": 0.0,
                "mrr": 0.0,
                "mean_latency_ms": 0.0,
            },
        )

    per_sample = [_evaluate_sample(sample, retrieve_top_k) for sample in samples]
    n = len(per_sample)
    metrics = {
        "recall_at_5": sum(r.recall_at_5 for r in per_sample) / n,
        "recall_at_10": sum(r.recall_at_10 for r in per_sample) / n,
        "precision_at_5": sum(r.precision_at_5 for r in per_sample) / n,
        "ndcg_at_10": sum(r.ndcg_at_10 for r in per_sample) / n,
        "mrr": sum(r.reciprocal_rank for r in per_sample) / n,
        "mean_latency_ms": round(sum(r.latency_ms for r in per_sample) / n, 2),
    }
    return RetrievalEvalReport(sample_count=n, metrics=metrics, per_sample=per_sample)


__all__ = [
    "PerSampleResult",
    "RetrievalEvalReport",
    "RetrievalSample",
    "run_retrieval_eval",
]
