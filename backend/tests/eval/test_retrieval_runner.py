"""End-to-end tests for the P2.5 retrieval runner.

Seeds a knowledge base via the test ``client`` fixture (real ingestion
pipeline, SQLite + noop vector store), then drives the runner and
asserts the report shape and plausibility. Does NOT pin absolute metric
values because deterministic embedding is stable but still noisy; we
only assert structural invariants.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models.knowledge import KnowledgeChunk
from app.db.session import bypass_rls_session
from app.services.eval.retrieval_runner import (
    RetrievalEvalReport,
    RetrievalSample,
    run_retrieval_eval,
)
from tests.conftest import DOCX_CONTENT_TYPE


def _seed_and_get_chunks(client, docx_file: bytes, tenant_id: str, customer_id: str) -> list[str]:
    """Upload a doc, return persisted chunk ids (for constructing relevant sets)."""
    response = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": tenant_id, "customer_id": customer_id},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert response.status_code == 202
    with bypass_rls_session() as session:
        rows = session.execute(
            select(KnowledgeChunk.id, KnowledgeChunk.content)
            .where(KnowledgeChunk.tenant_id == tenant_id)
            .where(KnowledgeChunk.customer_id == customer_id)
            .order_by(KnowledgeChunk.chunk_index)
        ).all()
    return [chunk_id for chunk_id, _ in rows]


def test_empty_samples_returns_zero_metrics() -> None:
    report = run_retrieval_eval([])
    assert isinstance(report, RetrievalEvalReport)
    assert report.sample_count == 0
    assert report.metrics["recall_at_5"] == 0.0
    assert report.metrics["mrr"] == 0.0


def test_retrieval_eval_populates_all_metrics(client, multilingual_docx_file: bytes) -> None:
    chunk_ids = _seed_and_get_chunks(
        client, multilingual_docx_file, "default-tenant", "default-customer"
    )
    assert chunk_ids, "seeding produced no chunks; ingestion pipeline may be broken"

    sample = RetrievalSample(
        query="北京酒店报销上限",
        tenant_id="default-tenant",
        customer_id="default-customer",
        # Mark the first persisted chunk as the target; deterministic
        # embedding plus lexical overlap should rank it within top-10.
        relevant_chunk_ids=(chunk_ids[0],),
    )
    report = run_retrieval_eval([sample], retrieve_top_k=10)

    assert report.sample_count == 1
    assert set(report.metrics) == {
        "recall_at_5",
        "recall_at_10",
        "precision_at_5",
        "ndcg_at_10",
        "mrr",
        "mean_latency_ms",
    }
    # Every metric should be in [0, 1] (latency is separate)
    for key in ("recall_at_5", "recall_at_10", "precision_at_5", "ndcg_at_10", "mrr"):
        assert 0.0 <= report.metrics[key] <= 1.0, f"{key}={report.metrics[key]}"
    assert report.metrics["mean_latency_ms"] >= 0.0
    # Per-sample breakdown must be present for the dashboard / later bisection.
    assert len(report.per_sample) == 1
    assert report.per_sample[0].query == "北京酒店报销上限"
