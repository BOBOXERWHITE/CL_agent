from types import SimpleNamespace

from sqlalchemy import select

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from app.services.rag import retrievers as retrievers_module
from app.services.rag.query_rewriter import rewrite_query
from app.services.rag.retrievers import (
    RetrievalHit,
    fuse_ranked_hits,
    retrieve_dense,
    retrieve_hybrid,
)


def test_hybrid_retrieval_prefers_exact_policy_keyword_matches(
    seeded_multilingual_policy_chunks: None,
) -> None:
    hits = retrieve_hybrid(
        "北京酒店报销上限是多少？",
        tenant_id="t1",
        customer_id="c1",
        top_k=3,
    )

    assert hits
    assert hits[0].document_title == "multilingual-policy"
    assert "北京酒店报销上限" in hits[0].content


def test_hybrid_retrieval_supports_mixed_language_question(
    seeded_multilingual_policy_chunks: None,
) -> None:
    hits = retrieve_hybrid(
        "business class 可以直接预订吗？",
        tenant_id="t1",
        customer_id="c1",
        top_k=3,
    )

    assert hits
    assert "economy class" in hits[0].content


def test_query_rewriter_expands_city_and_expense_aliases() -> None:
    rewritten = rewrite_query("北京住宿标准")

    assert "北京" in rewritten.expanded_query
    assert "酒店" in rewritten.expanded_query
    assert "报销上限" in rewritten.expanded_query


def test_retrieve_dense_uses_targeted_chunk_loading(
    seeded_multilingual_policy_chunks: None,
    monkeypatch,
) -> None:
    with SessionLocal() as session:
        row = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .limit(1)
        ).one()
    chunk, document = row

    class FakeVectorStore:
        def search(self, *, query_text: str, tenant_id: str, customer_id: str, top_k: int):
            assert tenant_id == "t1"
            assert customer_id == "c1"
            assert top_k >= 3
            return [(chunk.id, 0.83)]

    monkeypatch.setattr(retrievers_module, "get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setattr(
        retrievers_module,
        "_load_chunks",
        lambda tenant_id, customer_id: (_ for _ in ()).throw(
            AssertionError("dense retrieval should not full-scan chunks")
        ),
    )

    targeted_calls: list[list[str]] = []

    def fake_load_chunks_by_ids(tenant_id: str, customer_id: str, chunk_ids: list[str]):
        targeted_calls.append(chunk_ids)
        return [(chunk, document)]

    monkeypatch.setattr(
        retrievers_module, "_load_chunks_by_ids", fake_load_chunks_by_ids, raising=False
    )

    hits = retrieve_dense("北京酒店报销上限是多少？", "t1", "c1", 3)

    assert targeted_calls == [[chunk.id]]
    assert hits
    assert hits[0].chunk_id == chunk.id


def test_fuse_ranked_hits_uses_rrf_and_limits_duplicate_documents(
    seeded_multilingual_policy_chunks: None,
) -> None:
    dense_hits = [
        RetrievalHit(
            chunk=SimpleNamespace(id="chunk-1", content="北京酒店报销上限", title="住宿标准"),
            document=SimpleNamespace(id="doc-1", filename="policy-a.docx"),
            dense_score=0.91,
            lexical_score=0.0,
            combined_score=0.91,
        ),
        RetrievalHit(
            chunk=SimpleNamespace(id="chunk-2", content="北京住宿标准", title="住宿标准"),
            document=SimpleNamespace(id="doc-1", filename="policy-a.docx"),
            dense_score=0.82,
            lexical_score=0.0,
            combined_score=0.82,
        ),
    ]
    lexical_hits = [
        RetrievalHit(
            chunk=SimpleNamespace(id="chunk-2", content="北京住宿标准", title="住宿标准"),
            document=SimpleNamespace(id="doc-1", filename="policy-a.docx"),
            dense_score=0.0,
            lexical_score=0.95,
            combined_score=0.95,
        ),
        RetrievalHit(
            chunk=SimpleNamespace(id="chunk-3", content="商务舱审批要求", title="机票政策"),
            document=SimpleNamespace(id="doc-2", filename="policy-b.docx"),
            dense_score=0.0,
            lexical_score=0.72,
            combined_score=0.72,
        ),
    ]

    fused_hits = fuse_ranked_hits(
        dense_hits,
        lexical_hits,
        top_k=2,
        rrf_k=0,
        max_chunks_per_document=1,
    )

    assert len(fused_hits) == 2
    assert fused_hits[0].chunk_id == "chunk-2"
    assert fused_hits[1].document_id != fused_hits[0].document_id
