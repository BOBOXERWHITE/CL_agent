from app.services.rag.query_rewriter import rewrite_query
from app.services.rag.retrievers import retrieve_hybrid


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
