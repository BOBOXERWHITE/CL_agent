"""Query rewriting for RAG retrieval.

Three levels, combined at call time:

1. **Alias expansion** (always on, offline): hand-maintained synonyms
   for the travel-ops domain. Cheap, deterministic, no network.

2. **LLM paraphrase** (``QUERY_REWRITE_LLM_ENABLED``): ask the LLM for
   N alternative phrasings of the user's question. Each alt query can
   drive an extra retrieval pass; the caller fuses results via RRF.

3. **HyDE** (``HYDE_ENABLED``): hypothetical document embedding. We
   ask the LLM to *answer* the question in 1-2 sentences, then embed
   that hypothetical answer and retrieve with it. Good for vague queries
   where keywords don't match the chunk text directly.

Upstream failures in (2) or (3) are caught and logged -- the caller
gets the alias-only result and keeps working. This is defense in
depth: the LLM is a nice-to-have for retrieval quality, not a
correctness requirement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.rag.text_processing import normalize_text

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryRewriteResult:
    """Backward-compatible result for single-query callers."""

    original_query: str
    expanded_query: str
    applied_rules: list[str]


@dataclass(frozen=True)
class MultiQueryRewriteResult:
    """Full multi-channel result: alias + LLM variants + HyDE.

    Consumers that want to drive multi-query retrieval use this shape;
    ``QueryRewriteResult`` is a projection of it.
    """

    original_query: str
    expanded_query: str
    applied_rules: list[str]
    llm_variants: list[str] = field(default_factory=list)
    hyde_document: str | None = None

    def all_queries(self) -> list[str]:
        """Union of alias query + LLM variants, deduplicated."""
        queries = [self.expanded_query, *self.llm_variants]
        seen: set[str] = set()
        unique: list[str] = []
        for query in queries:
            stripped = query.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                unique.append(stripped)
        return unique


ALIAS_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("住宿别名", ("住宿", "住宿标准", "hotel"), ("酒店", "报销上限", "住宿标准")),
    ("舱位别名", ("business class", "商务舱"), ("economy class", "经济舱", "审批")),
    ("报销别名", ("reimbursement", "报销"), ("报销上限", "费用标准")),
)


def _apply_aliases(question: str) -> tuple[str, list[str]]:
    normalized = normalize_text(question)
    additions: list[str] = []
    applied_rules: list[str] = []
    for rule_name, triggers, expansions in ALIAS_RULES:
        if any(trigger in normalized for trigger in triggers):
            additions.extend(expansions)
            applied_rules.append(rule_name)
    expanded_query = " ".join(part for part in [question, *additions] if part).strip()
    return expanded_query, applied_rules


def rewrite_query(question: str) -> QueryRewriteResult:
    """Alias-only rewrite. Stable signature; kept for legacy callers."""
    expanded_query, applied_rules = _apply_aliases(question)
    return QueryRewriteResult(
        original_query=question,
        expanded_query=expanded_query,
        applied_rules=applied_rules,
    )


def rewrite_query_multi(
    question: str,
    *,
    llm_client: object | None = None,
    enable_llm_paraphrase: bool | None = None,
    enable_hyde: bool | None = None,
    paraphrase_variants: int | None = None,
) -> MultiQueryRewriteResult:
    """Alias + LLM paraphrase + HyDE rewrite.

    LLM-driven paths are best-effort: any exception downgrades that
    path silently (logged at WARNING). Alias expansion is always
    applied.

    Explicit keyword args override env config, which makes the function
    test-friendly without monkeypatching.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if enable_llm_paraphrase is None:
        enable_llm_paraphrase = settings.query_rewrite_llm_enabled
    if enable_hyde is None:
        enable_hyde = settings.hyde_enabled
    if paraphrase_variants is None:
        paraphrase_variants = settings.query_rewrite_llm_variants

    expanded_query, applied_rules = _apply_aliases(question)

    llm_variants: list[str] = []
    hyde_document: str | None = None

    if enable_llm_paraphrase or enable_hyde:
        client = llm_client if llm_client is not None else _default_rewrite_client()
        if client is None:
            applied_rules.append("llm_unavailable")
        else:
            if enable_llm_paraphrase and paraphrase_variants > 0:
                try:
                    variants = client.paraphrase(question, paraphrase_variants)  # type: ignore[attr-defined]
                    llm_variants = [
                        v for v in variants if v and v.strip() and v.strip() != question.strip()
                    ]
                    if llm_variants:
                        applied_rules.append("llm_paraphrase")
                except Exception as exc:
                    _log.warning(
                        "query_rewrite_llm_paraphrase_failed",
                        extra={"error": str(exc)},
                    )
            if enable_hyde:
                try:
                    hyde = client.generate_hyde_document(question)  # type: ignore[attr-defined]
                    if hyde and hyde.strip():
                        hyde_document = hyde.strip()
                        applied_rules.append("hyde")
                except Exception as exc:
                    _log.warning(
                        "query_rewrite_hyde_failed",
                        extra={"error": str(exc)},
                    )

    return MultiQueryRewriteResult(
        original_query=question,
        expanded_query=expanded_query,
        applied_rules=applied_rules,
        llm_variants=llm_variants,
        hyde_document=hyde_document,
    )


async def rewrite_query_multi_async(
    question: str,
    *,
    llm_client: object | None = None,
    enable_llm_paraphrase: bool | None = None,
    enable_hyde: bool | None = None,
    paraphrase_variants: int | None = None,
) -> MultiQueryRewriteResult:
    """Async twin of :func:`rewrite_query_multi` (P4.2).

    Uses ``paraphrase_async`` / ``generate_hyde_document_async`` when
    available on the client; silently degrades when the client only
    exposes the sync API (which would be a legacy shim, still supported).
    Same failure semantics: aliases are always applied, LLM paths are
    best-effort.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if enable_llm_paraphrase is None:
        enable_llm_paraphrase = settings.query_rewrite_llm_enabled
    if enable_hyde is None:
        enable_hyde = settings.hyde_enabled
    if paraphrase_variants is None:
        paraphrase_variants = settings.query_rewrite_llm_variants

    expanded_query, applied_rules = _apply_aliases(question)

    llm_variants: list[str] = []
    hyde_document: str | None = None

    if enable_llm_paraphrase or enable_hyde:
        client = llm_client if llm_client is not None else _default_rewrite_client()
        if client is None:
            applied_rules.append("llm_unavailable")
        else:
            if enable_llm_paraphrase and paraphrase_variants > 0:
                try:
                    paraphrase_async = getattr(client, "paraphrase_async", None)
                    if paraphrase_async is not None:
                        variants = await paraphrase_async(question, paraphrase_variants)
                    else:
                        # Legacy sync client — keep working by offloading.
                        import asyncio

                        variants = await asyncio.to_thread(
                            client.paraphrase,  # type: ignore[attr-defined]
                            question,
                            paraphrase_variants,
                        )
                    llm_variants = [
                        v for v in variants if v and v.strip() and v.strip() != question.strip()
                    ]
                    if llm_variants:
                        applied_rules.append("llm_paraphrase")
                except Exception as exc:
                    _log.warning(
                        "query_rewrite_llm_paraphrase_failed",
                        extra={"error": str(exc)},
                    )
            if enable_hyde:
                try:
                    hyde_async = getattr(client, "generate_hyde_document_async", None)
                    if hyde_async is not None:
                        hyde = await hyde_async(question)
                    else:
                        import asyncio

                        hyde = await asyncio.to_thread(
                            client.generate_hyde_document,  # type: ignore[attr-defined]
                            question,
                        )
                    if hyde and hyde.strip():
                        hyde_document = hyde.strip()
                        applied_rules.append("hyde")
                except Exception as exc:
                    _log.warning(
                        "query_rewrite_hyde_failed",
                        extra={"error": str(exc)},
                    )

    return MultiQueryRewriteResult(
        original_query=question,
        expanded_query=expanded_query,
        applied_rules=applied_rules,
        llm_variants=llm_variants,
        hyde_document=hyde_document,
    )


def _default_rewrite_client() -> object | None:
    """Resolve the process-wide rewrite LLM client.

    Lives in a helper so tests can inject a fake. Returns ``None`` when
    the LLM gateway is not configured, which degrades to alias-only.
    """
    try:
        from app.services.llm.rewrite_client import get_rewrite_client
    except Exception:  # pragma: no cover - defensive
        return None
    try:
        return get_rewrite_client()
    except Exception as exc:
        _log.warning("query_rewrite_client_unavailable", extra={"error": str(exc)})
        return None


__all__ = [
    "ALIAS_RULES",
    "MultiQueryRewriteResult",
    "QueryRewriteResult",
    "rewrite_query",
    "rewrite_query_multi",
    "rewrite_query_multi_async",
]
