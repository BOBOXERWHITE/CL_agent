from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import bypass_rls_session, init_db
from app.services.llm.client import get_policy_answer_client
from app.services.prompts.selector import select_prompt_variant
from app.services.prompts.service import PromptSelection
from app.services.rag.citation_service import CitationRecord, build_citations
from app.services.rag.query_rewriter import (
    MultiQueryRewriteResult,
    rewrite_query_multi,
)
from app.services.rag.rerankers import rerank_hits
from app.services.rag.retrievers import (
    RetrievalHit,
    fuse_ranked_hits,
    retrieve_dense,
    retrieve_hybrid,
    retrieve_lexical,
)
from app.services.rag.settings import get_rag_settings
from app.services.rag.text_processing import extract_cjk_sequences
from app.services.system_settings import get_effective_business_settings


@dataclass(frozen=True)
class PolicyAnswerResult:
    answer: str
    confidence: float
    citations: list[CitationRecord]
    retrieval_trace: RetrievalTrace
    prompt_template_id: str | None


@dataclass(frozen=True)
class StreamReadyContext:
    """P7.1: artifacts produced by ``prepare_answer_context_async`` when
    the request is about to hit the LLM.

    The streaming route uses these to ``yield`` citations / metadata
    before the first delta, and to reconstruct the canonical
    ``PolicyAnswerResult`` after the stream closes (so cache write-back
    and chat_message persistence use the exact same shape as the
    non-streaming endpoint).
    """

    prompt_selection: object  # PromptSelection; typed loosely to avoid cycle
    citations: list[CitationRecord]
    evidence_snippets: list[str]
    top_score: float
    rewritten_query: MultiQueryRewriteResult
    retrieval_mode: str
    retrieval_elapsed_ms: int
    candidate_count: int
    answer_cache_key: str
    client_model_name: str
    tenant_id: str
    question: str


@dataclass(frozen=True)
class RetrievalTraceChunk:
    chunk_id: str
    document_id: str
    document_title: str
    score: float


@dataclass(frozen=True)
class RetrievalTrace:
    mode: str
    prompt_name: str
    prompt_version: int
    model_name: str
    token_usage: dict[str, int]
    selected_chunks: list[RetrievalTraceChunk]
    original_query: str
    expanded_query: str
    rewrite_rules: list[str]
    candidate_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "prompt_name": self.prompt_name,
            "prompt_version": self.prompt_version,
            "model_name": self.model_name,
            "token_usage": self.token_usage,
            "selected_chunks": [
                {
                    "chunk_id": item.chunk_id,
                    "document_id": item.document_id,
                    "document_title": item.document_title,
                    "score": item.score,
                }
                for item in self.selected_chunks
            ],
            "original_query": self.original_query,
            "expanded_query": self.expanded_query,
            "rewrite_rules": self.rewrite_rules,
            "candidate_count": self.candidate_count,
        }


def _is_chinese_query(question: str) -> bool:
    return bool(extract_cjk_sequences(question))


def _load_chunk_map(
    chunk_ids: Iterable[str],
) -> dict[str, tuple[KnowledgeChunk, KnowledgeDocument]]:
    chunk_ids = list(chunk_ids)
    if not chunk_ids:
        return {}

    with bypass_rls_session() as session:
        rows = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.id.in_(chunk_ids))
        ).all()

    return {chunk.id: (chunk, document) for chunk, document in rows}


def _records_from_hits(
    hits: list[RetrievalHit],
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    return [(hit.chunk, hit.document, hit.combined_score) for hit in hits]


def _to_hit_records(
    records: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    for chunk, document, score in records:
        hits.append(
            RetrievalHit(
                chunk=chunk,
                document=document,
                dense_score=score,
                lexical_score=score,
                combined_score=score,
            )
        )
    return hits


def _multi_query_search(
    rewrite: MultiQueryRewriteResult,
    tenant_id: str,
    customer_id: str,
    top_k: int,
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    """Run hybrid retrieval for every rewrite channel + HyDE doc, then
    RRF-fuse the per-channel top-K lists.

    Channels:
    - every entry in ``rewrite.all_queries()`` (alias-expanded + LLM paraphrases)
    - if present, ``rewrite.hyde_document`` (treated as an extra query text
      so its embedding drives another retrieval pass)

    Fusion happens in the ``combined_score`` channel only; the per-hit
    ``dense_score`` / ``lexical_score`` we keep from the first appearance.
    Final result is reranked once via the configured reranker so both the
    fused ordering and the reranker's phrase/API bonus land on the output.

    No-LLM / alias-only mode collapses to a single call to ``retrieve_hybrid``
    (same path as the legacy ``_hybrid_search``) so there's no extra cost
    when multi-query flags are off.
    """
    rag_settings = get_rag_settings()
    queries: list[str] = list(rewrite.all_queries())
    # HyDE doc adds a retrieval channel; dedupe against existing.
    if rewrite.hyde_document and rewrite.hyde_document not in queries:
        queries.append(rewrite.hyde_document)

    # Zero queries (should never happen) → fall back to the original.
    if not queries:
        queries = [rewrite.original_query]

    # Fast path: single channel, skip the extra fusion round.
    if len(queries) == 1:
        hits = retrieve_hybrid(queries[0], tenant_id, customer_id, top_k)
        reranked = rerank_hits(queries[0], hits, top_k)
        return _records_from_hits(reranked)

    # Multi-query: run hybrid retrieval per channel, RRF fuse.
    per_channel: list[list[RetrievalHit]] = []
    for query in queries:
        per_channel.append(retrieve_hybrid(query, tenant_id, customer_id, top_k))

    fused = per_channel[0]
    for channel_hits in per_channel[1:]:
        fused = fuse_ranked_hits(
            fused,
            channel_hits,
            top_k=max(top_k * 2, top_k),  # keep slack for the reranker
            rrf_k=max(0, rag_settings.rrf_k),
            max_chunks_per_document=rag_settings.max_chunks_per_document,
        )

    reranked = rerank_hits(rewrite.original_query, fused, top_k)
    return _records_from_hits(reranked)


def _hybrid_search(
    question: str, tenant_id: str, customer_id: str, top_k: int
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    dense_records = _vector_search(question, tenant_id, customer_id, top_k)
    lexical_records = _lexical_search(question, tenant_id, customer_id, top_k)

    if not dense_records and not lexical_records:
        reranked = rerank_hits(
            question, retrieve_hybrid(question, tenant_id, customer_id, top_k), top_k
        )
        return _records_from_hits(reranked)

    merged: dict[str, RetrievalHit] = {}
    for hit in [*_to_hit_records(dense_records), *_to_hit_records(lexical_records)]:
        existing = merged.get(hit.chunk.id)
        if existing is None or hit.combined_score > existing.combined_score:
            merged[hit.chunk.id] = hit

    reranked = rerank_hits(question, list(merged.values()), top_k)
    return _records_from_hits(reranked)


def _lexical_search(
    question: str, tenant_id: str, customer_id: str, top_k: int
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    reranked = rerank_hits(
        question, retrieve_lexical(question, tenant_id, customer_id, top_k), top_k
    )
    return _records_from_hits(reranked)


def _vector_search(
    question: str, tenant_id: str, customer_id: str, top_k: int
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    reranked = rerank_hits(question, retrieve_dense(question, tenant_id, customer_id, top_k), top_k)
    return _records_from_hits(reranked)


def _build_trace(
    *,
    retrieval_mode: str,
    prompt_selection: PromptSelection,
    citations: list[CitationRecord],
    model_name: str,
    token_usage: dict[str, int],
    original_query: str,
    expanded_query: str,
    rewrite_rules: list[str],
    candidate_count: int,
) -> RetrievalTrace:
    selected_chunks = [
        RetrievalTraceChunk(
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            document_title=citation.document_title,
            score=citation.score,
        )
        for citation in citations
    ]
    return RetrievalTrace(
        mode=retrieval_mode,
        prompt_name=prompt_selection.name,
        prompt_version=prompt_selection.version,
        model_name=model_name,
        token_usage=token_usage,
        selected_chunks=selected_chunks,
        original_query=original_query,
        expanded_query=expanded_query,
        rewrite_rules=rewrite_rules,
        candidate_count=candidate_count,
    )


async def answer_policy_question_async(
    question: str, tenant_id: str, customer_id: str
) -> PolicyAnswerResult:
    """Async twin of :func:`answer_policy_question` (P4.2).

    Design rationale
    ----------------

    Only the two LLM hops (query rewrite + answer generation) are truly
    slow on the event loop. The Milvus / lexical retrieval path is
    either fast (< tens of ms) or stuck behind sync client APIs
    (``pymilvus``, SQLAlchemy sync session). Offloading those parts to
    ``asyncio.to_thread`` gives us:

    - Real concurrency on the two hot HTTP calls (via P4.1 + P4.2
      async clients)
    - Event-loop freedom on the sync blocks (the thread pool absorbs
      the waiting time instead of the uvicorn worker)
    - Zero rewrite of retriever / reranker / citation-builder code

    Functional parity with the sync ``answer_policy_question`` is
    mandatory: the two paths must return the same ``PolicyAnswerResult``
    for the same inputs. We keep the control flow byte-for-byte identical
    and only swap the two async calls.
    """
    import asyncio

    from app.core.observability.tracing import trace_span

    init_db()
    settings = get_settings()
    business_settings = get_effective_business_settings()
    answer_client = get_policy_answer_client()
    client_model_name = getattr(answer_client, "model_name", settings.llm_model_name)
    # P6.2: go through the A/B selector so candidate traffic splits are
    # honoured + the decision is logged. ``request_id`` comes from the
    # current trace context so the selection log rows stitch cleanly
    # to rag_recall_log / audit_log.
    from app.core.observability.tracing import current_trace_id

    request_id = current_trace_id() or ""
    with bypass_rls_session() as session:
        prompt_selection = select_prompt_variant(
            session,
            task_type="policy_answer",
            tenant_id=tenant_id,
            request_id=request_id,
        )

    # P5-patch-A: wrap the two LLM hops + the retrieval step in their
    # own spans so OTLP backends can attribute latency. The parent
    # relationship is implicit via trace_id context — we avoid a single
    # outer ``with`` block because the function has many early-return
    # branches and keeping them all inside an ``__exit__`` scope would
    # force a major indent refactor.

    # --- async hot path #1: query rewrite (LLM paraphrase + HyDE) ---
    from app.services.rag.query_rewriter import rewrite_query_multi_async

    with trace_span(
        "policy_qa.rewrite",
        tenant_id=tenant_id,
        question_length=len(question or ""),
    ):
        rewritten_query = await rewrite_query_multi_async(question)

    # --- sync retrieval path, offloaded to thread pool ---
    retrieval_started_at = perf_counter()
    retrieval_mode = (
        "multi_hybrid"
        if (rewritten_query.llm_variants or rewritten_query.hyde_document)
        else "hybrid"
    )
    with trace_span("policy_qa.retrieve.multi_query", mode=retrieval_mode):
        retrievals = await asyncio.to_thread(
            _multi_query_search,
            rewritten_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    if not retrievals:
        retrieval_mode = "vector"
        retrievals = await asyncio.to_thread(
            _vector_search,
            rewritten_query.expanded_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    if not retrievals:
        retrieval_mode = "lexical"
        retrievals = await asyncio.to_thread(
            _lexical_search,
            rewritten_query.expanded_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    retrieval_elapsed_ms = int((perf_counter() - retrieval_started_at) * 1000)

    citations = build_citations(retrievals)
    candidate_count = len(retrievals)
    if not citations:
        no_evidence_answer = (
            "当前没有检索到足够的政策证据，暂时无法给出可信回答。"
            if _is_chinese_query(question)
            else "I do not have enough policy evidence to answer this question confidently yet."
        )
        retrieval_trace = _build_trace(
            retrieval_mode=retrieval_mode,
            prompt_selection=prompt_selection,
            citations=[],
            model_name=client_model_name,
            token_usage={"input_tokens": 0, "output_tokens": 0},
            original_query=question,
            expanded_query=rewritten_query.expanded_query,
            rewrite_rules=rewritten_query.applied_rules,
            candidate_count=candidate_count,
        )
        return PolicyAnswerResult(
            answer=no_evidence_answer,
            confidence=0.0,
            citations=[],
            retrieval_trace=retrieval_trace,
            prompt_template_id=prompt_selection.id,
        )

    evidence_snippets = [citation.snippet for citation in citations]
    top_score = max(0.0, min(citations[0].score, 1.0))
    if top_score < business_settings.chat_confidence_threshold:
        low_confidence_answer = (
            "我找到了相关政策片段，但当前证据强度还不足以给出高置信回答。"
            if _is_chinese_query(question)
            else "I found related policy text, but the evidence is not strong enough for a confident answer yet."
        )
        retrieval_trace = _build_trace(
            retrieval_mode=retrieval_mode,
            prompt_selection=prompt_selection,
            citations=citations,
            model_name=client_model_name,
            token_usage={"input_tokens": 0, "output_tokens": 0},
            original_query=question,
            expanded_query=rewritten_query.expanded_query,
            rewrite_rules=rewritten_query.applied_rules,
            candidate_count=candidate_count,
        )
        return PolicyAnswerResult(
            answer=low_confidence_answer,
            confidence=round(top_score, 4),
            citations=citations,
            retrieval_trace=retrieval_trace,
            prompt_template_id=prompt_selection.id,
        )

    from app.core.cache import answer_cache_key, get_cache

    cache = get_cache()
    top_chunk_ids = [citation.chunk_id for citation in citations]
    answer_key = answer_cache_key(
        tenant_id=tenant_id,
        query_signature=f"{question}|{prompt_selection.version}",
        top_chunks_signature="|".join(top_chunk_ids),
    )
    cached_answer = cache.get(answer_key)
    if cached_answer and isinstance(cached_answer, dict) and cached_answer.get("answer"):
        retrieval_trace = _build_trace(
            retrieval_mode=f"{retrieval_mode}:cache_hit",
            prompt_selection=prompt_selection,
            citations=citations,
            model_name=str(cached_answer.get("model_name", client_model_name)),
            token_usage={"input_tokens": 0, "output_tokens": 0},
            original_query=question,
            expanded_query=rewritten_query.expanded_query,
            rewrite_rules=[*rewritten_query.applied_rules, "answer_cache_hit"],
            candidate_count=candidate_count,
        )
        return PolicyAnswerResult(
            answer=str(cached_answer["answer"]),
            confidence=round(float(cached_answer.get("confidence", top_score)), 4),
            citations=citations,
            retrieval_trace=retrieval_trace,
            prompt_template_id=prompt_selection.id,
        )

    # --- async hot path #2: answer generation ---
    generation_started_at = perf_counter()
    with trace_span(
        "policy_qa.generate",
        tenant_id=tenant_id,
        model=client_model_name,
        evidence_count=len(evidence_snippets),
    ) as gen_span:
        answer_draft = await answer_client.generate_answer_async(
            question=question,
            evidence_snippets=evidence_snippets,
            confidence=top_score,
            prompt_template=prompt_selection.template,
        )
        # Attach usage after the call so the OTLP backend can attribute
        # tokens to this exact span (billing-grade trace view).
        gen_span.set_attr("input_tokens", int(answer_draft.token_usage.get("input_tokens", 0)))
        gen_span.set_attr("output_tokens", int(answer_draft.token_usage.get("output_tokens", 0)))
    generation_elapsed_ms = int((perf_counter() - generation_started_at) * 1000)

    if (
        answer_draft.answer
        and answer_draft.confidence >= business_settings.chat_confidence_threshold
    ):
        try:
            cache.set(
                answer_key,
                {
                    "answer": answer_draft.answer,
                    "confidence": float(answer_draft.confidence),
                    "model_name": answer_draft.model_name,
                },
                ttl_seconds=settings.cache_answer_ttl_seconds,
            )
        except (TypeError, ValueError):
            pass
    retrieval_trace = _build_trace(
        retrieval_mode=f"{retrieval_mode}:{retrieval_elapsed_ms}ms/{generation_elapsed_ms}ms",
        prompt_selection=prompt_selection,
        citations=citations,
        model_name=answer_draft.model_name,
        token_usage=answer_draft.token_usage,
        original_query=question,
        expanded_query=rewritten_query.expanded_query,
        rewrite_rules=rewritten_query.applied_rules,
        candidate_count=candidate_count,
    )
    return PolicyAnswerResult(
        answer=answer_draft.answer,
        confidence=round(answer_draft.confidence, 4),
        citations=citations,
        retrieval_trace=retrieval_trace,
        prompt_template_id=prompt_selection.id,
    )


def answer_policy_question(question: str, tenant_id: str, customer_id: str) -> PolicyAnswerResult:
    init_db()
    settings = get_settings()
    business_settings = get_effective_business_settings()
    answer_client = get_policy_answer_client()
    client_model_name = getattr(answer_client, "model_name", settings.llm_model_name)
    # P6.2: same A/B selector as the async path so sync callers
    # (Celery worker, eval runner, scripts) also respect traffic splits
    # and get logged.
    from app.core.observability.tracing import current_trace_id

    request_id = current_trace_id() or ""
    with bypass_rls_session() as session:
        prompt_selection = select_prompt_variant(
            session,
            task_type="policy_answer",
            tenant_id=tenant_id,
            request_id=request_id,
        )

    rewritten_query = rewrite_query_multi(question)
    retrieval_started_at = perf_counter()
    retrieval_mode = (
        "multi_hybrid"
        if (rewritten_query.llm_variants or rewritten_query.hyde_document)
        else "hybrid"
    )
    retrievals = _multi_query_search(
        rewritten_query,
        tenant_id,
        customer_id,
        business_settings.chat_top_k,
    )
    if not retrievals:
        retrieval_mode = "vector"
        retrievals = _vector_search(
            rewritten_query.expanded_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    if not retrievals:
        retrieval_mode = "lexical"
        retrievals = _lexical_search(
            rewritten_query.expanded_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    retrieval_elapsed_ms = int((perf_counter() - retrieval_started_at) * 1000)

    citations = build_citations(retrievals)
    candidate_count = len(retrievals)
    if not citations:
        no_evidence_answer = (
            "当前没有检索到足够的政策证据，暂时无法给出可信回答。"
            if _is_chinese_query(question)
            else "I do not have enough policy evidence to answer this question confidently yet."
        )
        retrieval_trace = _build_trace(
            retrieval_mode=retrieval_mode,
            prompt_selection=prompt_selection,
            citations=[],
            model_name=client_model_name,
            token_usage={"input_tokens": 0, "output_tokens": 0},
            original_query=question,
            expanded_query=rewritten_query.expanded_query,
            rewrite_rules=rewritten_query.applied_rules,
            candidate_count=candidate_count,
        )
        return PolicyAnswerResult(
            answer=no_evidence_answer,
            confidence=0.0,
            citations=[],
            retrieval_trace=retrieval_trace,
            prompt_template_id=prompt_selection.id,
        )

    evidence_snippets = [citation.snippet for citation in citations]
    top_score = max(0.0, min(citations[0].score, 1.0))
    if top_score < business_settings.chat_confidence_threshold:
        low_confidence_answer = (
            "我找到了相关政策片段，但当前证据强度还不足以给出高置信回答。"
            if _is_chinese_query(question)
            else "I found related policy text, but the evidence is not strong enough for a confident answer yet."
        )
        retrieval_trace = _build_trace(
            retrieval_mode=retrieval_mode,
            prompt_selection=prompt_selection,
            citations=citations,
            model_name=client_model_name,
            token_usage={"input_tokens": 0, "output_tokens": 0},
            original_query=question,
            expanded_query=rewritten_query.expanded_query,
            rewrite_rules=rewritten_query.applied_rules,
            candidate_count=candidate_count,
        )
        return PolicyAnswerResult(
            answer=low_confidence_answer,
            confidence=round(top_score, 4),
            citations=citations,
            retrieval_trace=retrieval_trace,
            prompt_template_id=prompt_selection.id,
        )

    # Answer cache (P2.7 接入): same tenant + same question + same top
    # chunks → reuse the previous LLM answer. The key includes the
    # prompt version so prompt rollouts invalidate automatically.
    from app.core.cache import answer_cache_key, get_cache

    cache = get_cache()
    top_chunk_ids = [citation.chunk_id for citation in citations]
    answer_key = answer_cache_key(
        tenant_id=tenant_id,
        query_signature=f"{question}|{prompt_selection.version}",
        top_chunks_signature="|".join(top_chunk_ids),
    )
    cached_answer = cache.get(answer_key)
    if cached_answer and isinstance(cached_answer, dict) and cached_answer.get("answer"):
        retrieval_trace = _build_trace(
            retrieval_mode=f"{retrieval_mode}:cache_hit",
            prompt_selection=prompt_selection,
            citations=citations,
            model_name=str(cached_answer.get("model_name", client_model_name)),
            token_usage={"input_tokens": 0, "output_tokens": 0},  # cached: no new tokens
            original_query=question,
            expanded_query=rewritten_query.expanded_query,
            rewrite_rules=[*rewritten_query.applied_rules, "answer_cache_hit"],
            candidate_count=candidate_count,
        )
        return PolicyAnswerResult(
            answer=str(cached_answer["answer"]),
            confidence=round(float(cached_answer.get("confidence", top_score)), 4),
            citations=citations,
            retrieval_trace=retrieval_trace,
            prompt_template_id=prompt_selection.id,
        )

    generation_started_at = perf_counter()
    answer_draft = answer_client.generate_answer(
        question=question,
        evidence_snippets=evidence_snippets,
        confidence=top_score,
        prompt_template=prompt_selection.template,
    )
    generation_elapsed_ms = int((perf_counter() - generation_started_at) * 1000)

    # Write-through: only cache high-confidence answers so we don't pin
    # "not enough evidence" phrasings against stale retrievals.
    if (
        answer_draft.answer
        and answer_draft.confidence >= business_settings.chat_confidence_threshold
    ):
        try:
            cache.set(
                answer_key,
                {
                    "answer": answer_draft.answer,
                    "confidence": float(answer_draft.confidence),
                    "model_name": answer_draft.model_name,
                },
                ttl_seconds=settings.cache_answer_ttl_seconds,
            )
        except (TypeError, ValueError):
            # Defensive: never fail the chat path because of cache serialisation.
            pass
    retrieval_trace = _build_trace(
        retrieval_mode=f"{retrieval_mode}:{retrieval_elapsed_ms}ms/{generation_elapsed_ms}ms",
        prompt_selection=prompt_selection,
        citations=citations,
        model_name=answer_draft.model_name,
        token_usage=answer_draft.token_usage,
        original_query=question,
        expanded_query=rewritten_query.expanded_query,
        rewrite_rules=rewritten_query.applied_rules,
        candidate_count=candidate_count,
    )
    return PolicyAnswerResult(
        answer=answer_draft.answer,
        confidence=round(answer_draft.confidence, 4),
        citations=citations,
        retrieval_trace=retrieval_trace,
        prompt_template_id=prompt_selection.id,
    )


# ---------------------------------------------------------------------------
# P7.1: split the async path so streaming routes can start pushing
# citations + tokens as soon as the retrieval / cache step is done,
# without waiting for the full generation. The non-streaming path above
# keeps its byte-for-byte control flow so sync/async parity tests stay
# stable.
# ---------------------------------------------------------------------------


async def prepare_answer_context_async(
    question: str, tenant_id: str, customer_id: str
) -> PolicyAnswerResult | StreamReadyContext:
    """P7.1 prep phase: rewrite + retrieve + cache check.

    Returns either:

    - ``PolicyAnswerResult`` — one of the three early-exit branches
      (no evidence / low confidence / answer cache hit). The stream
      route turns this into a single ``delta`` + ``done`` SSE pair.
    - ``StreamReadyContext`` — ready for generation. The stream route
      yields ``citations`` then iterates ``stream_answer_from_context``.
    """
    import asyncio

    from app.core.observability.tracing import current_trace_id, trace_span

    init_db()
    settings = get_settings()
    business_settings = get_effective_business_settings()
    answer_client = get_policy_answer_client()
    client_model_name = getattr(answer_client, "model_name", settings.llm_model_name)

    request_id = current_trace_id() or ""
    with bypass_rls_session() as session:
        prompt_selection = select_prompt_variant(
            session,
            task_type="policy_answer",
            tenant_id=tenant_id,
            request_id=request_id,
        )

    from app.services.rag.query_rewriter import rewrite_query_multi_async

    with trace_span(
        "policy_qa.rewrite",
        tenant_id=tenant_id,
        question_length=len(question or ""),
    ):
        rewritten_query = await rewrite_query_multi_async(question)

    retrieval_started_at = perf_counter()
    retrieval_mode = (
        "multi_hybrid"
        if (rewritten_query.llm_variants or rewritten_query.hyde_document)
        else "hybrid"
    )
    with trace_span("policy_qa.retrieve.multi_query", mode=retrieval_mode):
        retrievals = await asyncio.to_thread(
            _multi_query_search,
            rewritten_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    if not retrievals:
        retrieval_mode = "vector"
        retrievals = await asyncio.to_thread(
            _vector_search,
            rewritten_query.expanded_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    if not retrievals:
        retrieval_mode = "lexical"
        retrievals = await asyncio.to_thread(
            _lexical_search,
            rewritten_query.expanded_query,
            tenant_id,
            customer_id,
            business_settings.chat_top_k,
        )
    retrieval_elapsed_ms = int((perf_counter() - retrieval_started_at) * 1000)

    citations = build_citations(retrievals)
    candidate_count = len(retrievals)

    # Early exit: no evidence.
    if not citations:
        no_evidence_answer = (
            "当前没有检索到足够的政策证据，暂时无法给出可信回答。"
            if _is_chinese_query(question)
            else "I do not have enough policy evidence to answer this question confidently yet."
        )
        return PolicyAnswerResult(
            answer=no_evidence_answer,
            confidence=0.0,
            citations=[],
            retrieval_trace=_build_trace(
                retrieval_mode=retrieval_mode,
                prompt_selection=prompt_selection,
                citations=[],
                model_name=client_model_name,
                token_usage={"input_tokens": 0, "output_tokens": 0},
                original_query=question,
                expanded_query=rewritten_query.expanded_query,
                rewrite_rules=rewritten_query.applied_rules,
                candidate_count=candidate_count,
            ),
            prompt_template_id=prompt_selection.id,
        )

    evidence_snippets = [citation.snippet for citation in citations]
    top_score = max(0.0, min(citations[0].score, 1.0))

    # Early exit: low confidence.
    if top_score < business_settings.chat_confidence_threshold:
        low_confidence_answer = (
            "我找到了相关政策片段，但当前证据强度还不足以给出高置信回答。"
            if _is_chinese_query(question)
            else "I found related policy text, but the evidence is not strong enough for a confident answer yet."
        )
        return PolicyAnswerResult(
            answer=low_confidence_answer,
            confidence=round(top_score, 4),
            citations=citations,
            retrieval_trace=_build_trace(
                retrieval_mode=retrieval_mode,
                prompt_selection=prompt_selection,
                citations=citations,
                model_name=client_model_name,
                token_usage={"input_tokens": 0, "output_tokens": 0},
                original_query=question,
                expanded_query=rewritten_query.expanded_query,
                rewrite_rules=rewritten_query.applied_rules,
                candidate_count=candidate_count,
            ),
            prompt_template_id=prompt_selection.id,
        )

    # Early exit: cache hit.
    from app.core.cache import answer_cache_key, get_cache

    cache = get_cache()
    top_chunk_ids = [citation.chunk_id for citation in citations]
    cache_key = answer_cache_key(
        tenant_id=tenant_id,
        query_signature=f"{question}|{prompt_selection.version}",
        top_chunks_signature="|".join(top_chunk_ids),
    )
    cached_answer = cache.get(cache_key)
    if cached_answer and isinstance(cached_answer, dict) and cached_answer.get("answer"):
        return PolicyAnswerResult(
            answer=str(cached_answer["answer"]),
            confidence=round(float(cached_answer.get("confidence", top_score)), 4),
            citations=citations,
            retrieval_trace=_build_trace(
                retrieval_mode=f"{retrieval_mode}:cache_hit",
                prompt_selection=prompt_selection,
                citations=citations,
                model_name=str(cached_answer.get("model_name", client_model_name)),
                token_usage={"input_tokens": 0, "output_tokens": 0},
                original_query=question,
                expanded_query=rewritten_query.expanded_query,
                rewrite_rules=[*rewritten_query.applied_rules, "answer_cache_hit"],
                candidate_count=candidate_count,
            ),
            prompt_template_id=prompt_selection.id,
        )

    # No early exit → caller can stream.
    return StreamReadyContext(
        prompt_selection=prompt_selection,
        citations=citations,
        evidence_snippets=evidence_snippets,
        top_score=top_score,
        rewritten_query=rewritten_query,
        retrieval_mode=retrieval_mode,
        retrieval_elapsed_ms=retrieval_elapsed_ms,
        candidate_count=candidate_count,
        answer_cache_key=cache_key,
        client_model_name=client_model_name,
        tenant_id=tenant_id,
        question=question,
    )


async def stream_answer_from_context(context: StreamReadyContext):
    """P7.1 generation phase: yield ``StreamChunk`` from the LLM.

    Last chunk has ``done=True`` with ``token_usage`` + ``model_name``.
    Caller owns cache write-through + persistence via
    :func:`build_policy_answer_from_stream`.
    """
    answer_client = get_policy_answer_client()
    async for chunk in answer_client.stream_answer_async(
        question=context.question,
        evidence_snippets=context.evidence_snippets,
        confidence=context.top_score,
        prompt_template=context.prompt_selection.template,  # type: ignore[attr-defined]
    ):
        yield chunk


def build_policy_answer_from_stream(
    context: StreamReadyContext,
    *,
    collected_text: str,
    token_usage: dict[str, int],
    model_name: str,
    generation_elapsed_ms: int,
) -> PolicyAnswerResult:
    """Reconstruct the canonical ``PolicyAnswerResult`` after a stream
    closes and write-through the answer cache. Mirrors the non-streaming
    cache branch in :func:`answer_policy_question_async`.
    """
    from app.core.cache import get_cache

    cache = get_cache()
    business_settings = get_effective_business_settings()
    final_confidence = round(context.top_score, 4)
    if collected_text and final_confidence >= business_settings.chat_confidence_threshold:
        try:
            cache.set(
                context.answer_cache_key,
                {
                    "answer": collected_text,
                    "confidence": float(final_confidence),
                    "model_name": model_name,
                },
                ttl_seconds=get_settings().cache_answer_ttl_seconds,
            )
        except (TypeError, ValueError):
            pass

    retrieval_trace = _build_trace(
        retrieval_mode=(
            f"{context.retrieval_mode}:{context.retrieval_elapsed_ms}ms/{generation_elapsed_ms}ms"
        ),
        prompt_selection=context.prompt_selection,  # type: ignore[arg-type]
        citations=context.citations,
        model_name=model_name or context.client_model_name,
        token_usage=token_usage,
        original_query=context.question,
        expanded_query=context.rewritten_query.expanded_query,
        rewrite_rules=context.rewritten_query.applied_rules,
        candidate_count=context.candidate_count,
    )
    return PolicyAnswerResult(
        answer=collected_text,
        confidence=final_confidence,
        citations=context.citations,
        retrieval_trace=retrieval_trace,
        prompt_template_id=context.prompt_selection.id,  # type: ignore[attr-defined]
    )
