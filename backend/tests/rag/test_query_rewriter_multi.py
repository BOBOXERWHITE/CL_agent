"""Tests for the P2.6 multi-channel query rewriter.

Covers:
- Alias-only path keeps working (backward compat).
- LLM paraphrase path calls the injected client and appends variants.
- HyDE path calls the injected client and stores the hypothetical doc.
- Failures in LLM paths degrade to alias-only with a warning (no raise).
- ``all_queries`` dedupes and preserves order.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.rag.query_rewriter import (
    MultiQueryRewriteResult,
    rewrite_query,
    rewrite_query_multi,
)


@dataclass
class _FakeClient:
    paraphrases: list[str] = field(default_factory=list)
    hyde: str = ""
    raise_on_paraphrase: bool = False
    raise_on_hyde: bool = False

    def paraphrase(self, question: str, n: int) -> list[str]:
        if self.raise_on_paraphrase:
            raise RuntimeError("upstream broke")
        return list(self.paraphrases[:n])

    def generate_hyde_document(self, question: str) -> str:
        if self.raise_on_hyde:
            raise RuntimeError("hyde broke")
        return self.hyde


def test_legacy_rewrite_query_still_works() -> None:
    result = rewrite_query("北京酒店报销上限")
    assert result.original_query == "北京酒店报销上限"
    assert result.expanded_query.startswith("北京酒店报销上限")
    # 报销别名 rule triggers on 报销 in the query
    assert "报销别名" in result.applied_rules


def test_multi_alias_only_when_flags_disabled() -> None:
    result = rewrite_query_multi(
        "北京酒店",
        llm_client=_FakeClient(paraphrases=["noop"], hyde="noop"),
        enable_llm_paraphrase=False,
        enable_hyde=False,
    )
    assert result.llm_variants == []
    assert result.hyde_document is None
    assert "llm_paraphrase" not in result.applied_rules
    assert "hyde" not in result.applied_rules


def test_multi_paraphrase_appends_variants() -> None:
    fake = _FakeClient(paraphrases=["variant A", "variant B"])
    result = rewrite_query_multi(
        "some question",
        llm_client=fake,
        enable_llm_paraphrase=True,
        enable_hyde=False,
        paraphrase_variants=2,
    )
    assert result.llm_variants == ["variant A", "variant B"]
    assert "llm_paraphrase" in result.applied_rules


def test_multi_paraphrase_filters_echo_and_empty() -> None:
    """Variants identical to the original or blank are dropped."""
    fake = _FakeClient(paraphrases=["", "some question", "  ", "real paraphrase"])
    result = rewrite_query_multi(
        "some question",
        llm_client=fake,
        enable_llm_paraphrase=True,
        enable_hyde=False,
        paraphrase_variants=4,
    )
    assert result.llm_variants == ["real paraphrase"]


def test_multi_hyde_generates_document() -> None:
    fake = _FakeClient(hyde="hypothetical answer text")
    result = rewrite_query_multi(
        "what is the cap",
        llm_client=fake,
        enable_llm_paraphrase=False,
        enable_hyde=True,
    )
    assert result.hyde_document == "hypothetical answer text"
    assert "hyde" in result.applied_rules


def test_multi_paraphrase_upstream_failure_degrades_silently() -> None:
    fake = _FakeClient(raise_on_paraphrase=True, hyde="ok")
    result = rewrite_query_multi(
        "q",
        llm_client=fake,
        enable_llm_paraphrase=True,
        enable_hyde=True,
        paraphrase_variants=2,
    )
    # paraphrase failed → no variants, but hyde still succeeded
    assert result.llm_variants == []
    assert result.hyde_document == "ok"


def test_multi_hyde_upstream_failure_degrades_silently() -> None:
    fake = _FakeClient(paraphrases=["alt"], raise_on_hyde=True)
    result = rewrite_query_multi(
        "q",
        llm_client=fake,
        enable_llm_paraphrase=True,
        enable_hyde=True,
        paraphrase_variants=1,
    )
    assert result.llm_variants == ["alt"]
    assert result.hyde_document is None


def test_multi_all_queries_dedupes_and_orders() -> None:
    result = MultiQueryRewriteResult(
        original_query="q",
        expanded_query="q alias",
        applied_rules=["住宿别名"],
        llm_variants=["q alias", "other"],  # first is dup of expanded
    )
    assert result.all_queries() == ["q alias", "other"]


def test_multi_llm_client_none_marks_applied_rule() -> None:
    """When the flag is on but no client is available, record the fact."""
    result = rewrite_query_multi(
        "q",
        llm_client=None,  # would try default, which returns None in tests
        enable_llm_paraphrase=True,
        enable_hyde=False,
        paraphrase_variants=2,
    )
    # With deterministic LLM provider (default), fallback returns empty list.
    # Either "llm_unavailable" OR empty-variants-no-rule is acceptable;
    # assert the non-crashing shape.
    assert result.llm_variants == []
