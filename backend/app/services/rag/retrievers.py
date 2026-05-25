from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.observability.agent_tracing import retriever_span
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import bypass_rls_session
from app.services.rag.query_rewriter import rewrite_query as rewrite_query
from app.services.rag.settings import get_rag_settings
from app.services.rag.text_processing import build_search_terms, normalize_text
from app.services.rag.vector_store import get_vector_store

_log = logging.getLogger(__name__)

# P6: Known values for ``settings.lexical_backend``. Unknown values fall
# back to the legacy ILIKE path with a warning so a typo in env vars
# cannot dark-launch BM25 against a non-migrated collection.
_LEXICAL_BACKEND_ILIKE = "ilike"
_LEXICAL_BACKEND_MILVUS_BM25 = "milvus_bm25"
_KNOWN_LEXICAL_BACKENDS = frozenset({_LEXICAL_BACKEND_ILIKE, _LEXICAL_BACKEND_MILVUS_BM25})


@dataclass(frozen=True)
class RetrievalHit:
    chunk: KnowledgeChunk
    document: KnowledgeDocument
    dense_score: float
    lexical_score: float
    combined_score: float

    @property
    def chunk_id(self) -> str:
        return self.chunk.id

    @property
    def document_id(self) -> str:
        return self.document.id

    @property
    def document_title(self) -> str:
        return self.document.filename.rsplit(".", 1)[0] or self.document.filename

    @property
    def content(self) -> str:
        return self.chunk.content


def lexical_overlap_score(query: str, content: str, title: str) -> float:
    query_terms = set(build_search_terms(query))
    if not query_terms:
        return 0.0

    content_terms = set(build_search_terms(content))
    title_terms = set(build_search_terms(title))
    overlap = len(query_terms & content_terms) / len(query_terms)
    title_overlap = len(query_terms & title_terms) / len(query_terms)

    normalized_query = normalize_text(query)
    normalized_content = normalize_text(content)
    normalized_title = normalize_text(title)

    phrase_bonus = 0.0
    if normalized_query and normalized_query in normalized_content:
        phrase_bonus += 0.35
    if normalized_query and normalized_query in normalized_title:
        phrase_bonus += 0.2

    return overlap + title_overlap * 0.2 + phrase_bonus


def _load_chunks_by_ids(
    tenant_id: str,
    customer_id: str,
    chunk_ids: list[str],
) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
    if not chunk_ids:
        return []

    with bypass_rls_session() as session:
        rows = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.id.in_(chunk_ids))
            .where(KnowledgeChunk.tenant_id == tenant_id)
            .where(KnowledgeChunk.customer_id == customer_id)
            .where(KnowledgeDocument.status == "completed")
        ).all()
    return list(rows)


def _load_chunks(
    tenant_id: str, customer_id: str
) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
    with bypass_rls_session() as session:
        rows = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.tenant_id == tenant_id)
            .where(KnowledgeChunk.customer_id == customer_id)
            .where(KnowledgeDocument.status == "completed")
        ).all()
    return list(rows)


def _select_candidate_terms(query_text: str, limit: int = 12) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for term in sorted(build_search_terms(query_text), key=lambda item: (-len(item), item)):
        normalized_term = term.strip()
        if len(normalized_term) < 2 or normalized_term in seen:
            continue
        seen.add(normalized_term)
        candidates.append(normalized_term)
        if len(candidates) >= limit:
            break
    return candidates


def _load_lexical_candidates(
    tenant_id: str,
    customer_id: str,
    query_text: str,
    limit: int,
) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
    candidate_terms = _select_candidate_terms(query_text)
    if not candidate_terms:
        return []

    conditions = []
    for term in candidate_terms:
        like_pattern = f"%{term}%"
        conditions.extend(
            [
                KnowledgeChunk.content.ilike(like_pattern),
                KnowledgeChunk.title.ilike(like_pattern),
                KnowledgeDocument.filename.ilike(like_pattern),
            ]
        )

    with bypass_rls_session() as session:
        rows = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.tenant_id == tenant_id)
            .where(KnowledgeChunk.customer_id == customer_id)
            .where(KnowledgeDocument.status == "completed")
            .where(or_(*conditions))
            .limit(limit)
        ).all()
    return list(rows)


def _reciprocal_rank(rank: int, rrf_k: int) -> float:
    return 1.0 / (rrf_k + rank)


def _apply_document_diversity(
    hits: list[RetrievalHit],
    *,
    top_k: int,
    max_chunks_per_document: int,
) -> list[RetrievalHit]:
    selected: list[RetrievalHit] = []
    per_document_counts: dict[str, int] = {}

    for hit in hits:
        current_count = per_document_counts.get(hit.document_id, 0)
        if current_count >= max_chunks_per_document:
            continue
        selected.append(hit)
        per_document_counts[hit.document_id] = current_count + 1
        if len(selected) >= top_k:
            break
    return selected


def fuse_ranked_hits(
    dense_hits: list[RetrievalHit],
    lexical_hits: list[RetrievalHit],
    *,
    top_k: int,
    rrf_k: int,
    max_chunks_per_document: int,
) -> list[RetrievalHit]:
    merged: dict[str, RetrievalHit] = {}
    fused_scores: dict[str, float] = {}

    for rank, hit in enumerate(dense_hits, start=1):
        fused_scores[hit.chunk_id] = fused_scores.get(hit.chunk_id, 0.0) + _reciprocal_rank(
            rank, rrf_k
        )
        merged[hit.chunk_id] = hit

    for rank, hit in enumerate(lexical_hits, start=1):
        fused_scores[hit.chunk_id] = fused_scores.get(hit.chunk_id, 0.0) + _reciprocal_rank(
            rank, rrf_k
        )
        existing = merged.get(hit.chunk_id)
        if existing is None:
            merged[hit.chunk_id] = hit
            continue
        merged[hit.chunk_id] = RetrievalHit(
            chunk=existing.chunk,
            document=existing.document,
            dense_score=max(existing.dense_score, hit.dense_score),
            lexical_score=max(existing.lexical_score, hit.lexical_score),
            combined_score=max(existing.combined_score, hit.combined_score),
        )

    reranked_hits = [
        RetrievalHit(
            chunk=hit.chunk,
            document=hit.document,
            dense_score=hit.dense_score,
            lexical_score=hit.lexical_score,
            combined_score=fused_scores[chunk_id],
        )
        for chunk_id, hit in merged.items()
    ]
    reranked_hits.sort(
        key=lambda item: (item.combined_score, item.lexical_score, item.dense_score),
        reverse=True,
    )
    return _apply_document_diversity(
        reranked_hits,
        top_k=top_k,
        max_chunks_per_document=max(1, max_chunks_per_document),
    )


def retrieve_lexical(
    question: str, tenant_id: str, customer_id: str, top_k: int
) -> list[RetrievalHit]:
    rag_settings = get_rag_settings()
    candidate_limit = max(top_k * rag_settings.lexical_candidate_multiplier, 24)
    rows = _load_lexical_candidates(tenant_id, customer_id, question, candidate_limit)
    hits: list[RetrievalHit] = []

    for chunk, document in rows:
        score = lexical_overlap_score(question, chunk.content, chunk.title)
        if score <= 0:
            continue
        hits.append(
            RetrievalHit(
                chunk=chunk,
                document=document,
                dense_score=0.0,
                lexical_score=score,
                combined_score=score,
            )
        )

    hits.sort(key=lambda item: item.combined_score, reverse=True)
    return hits[: max(top_k * 2, top_k)]


def retrieve_lexical_milvus(
    question: str, tenant_id: str, customer_id: str, top_k: int
) -> list[RetrievalHit]:
    """P6: lexical retrieval via Milvus 2.5+ native BM25.

    Mirrors :func:`retrieve_lexical`'s return shape so the hybrid
    fusion + diversity layer downstream stays unchanged. The actual
    BM25 scoring happens server-side in Milvus (inverted index +
    Okapi formula); this function just (a) calls the vector store,
    (b) loads chunk + document rows from PG by id, (c) wraps each
    hit as a ``RetrievalHit`` with the BM25 score in ``lexical_score``.

    Chunks that vanished from PG between Milvus insert and now (e.g.
    document deleted but Milvus row not GC'd) are dropped silently
    instead of crashing — matches ``retrieve_dense``'s behaviour.
    """
    rag_settings = get_rag_settings()
    candidate_limit = max(top_k * rag_settings.lexical_candidate_multiplier, top_k)
    bm25_hits = get_vector_store().search_bm25(
        query_text=question,
        tenant_id=tenant_id,
        customer_id=customer_id,
        top_k=candidate_limit,
    )
    if not bm25_hits:
        return []

    chunk_ids = [chunk_id for chunk_id, _ in bm25_hits]
    chunk_map = {
        chunk.id: (chunk, document)
        for chunk, document in _load_chunks_by_ids(tenant_id, customer_id, chunk_ids)
    }

    hits: list[RetrievalHit] = []
    for chunk_id, bm25_score in bm25_hits:
        pair = chunk_map.get(chunk_id)
        if pair is None:
            continue
        chunk, document = pair
        hits.append(
            RetrievalHit(
                chunk=chunk,
                document=document,
                dense_score=0.0,
                lexical_score=bm25_score,
                combined_score=bm25_score,
            )
        )
    return hits


def retrieve_dense(
    question: str, tenant_id: str, customer_id: str, top_k: int
) -> list[RetrievalHit]:
    rag_settings = get_rag_settings()
    candidate_limit = max(top_k * rag_settings.dense_candidate_multiplier, top_k)
    vector_hits = get_vector_store().search(
        query_text=question,
        tenant_id=tenant_id,
        customer_id=customer_id,
        top_k=candidate_limit,
    )
    if not vector_hits:
        return []

    chunk_ids = [chunk_id for chunk_id, _ in vector_hits]
    chunk_map = {
        chunk.id: (chunk, document)
        for chunk, document in _load_chunks_by_ids(tenant_id, customer_id, chunk_ids)
    }
    hits: list[RetrievalHit] = []
    for chunk_id, dense_score in vector_hits:
        if chunk_id not in chunk_map:
            continue
        chunk, document = chunk_map[chunk_id]
        lexical_score = lexical_overlap_score(question, chunk.content, chunk.title)
        hits.append(
            RetrievalHit(
                chunk=chunk,
                document=document,
                dense_score=dense_score,
                lexical_score=lexical_score,
                combined_score=dense_score,
            )
        )

    hits.sort(key=lambda item: item.combined_score, reverse=True)
    return hits[:candidate_limit]


def retrieve_hybrid(
    question: str, tenant_id: str, customer_id: str, top_k: int
) -> list[RetrievalHit]:
    rag_settings = get_rag_settings()
    settings = get_settings()
    # P6: pick lexical backend at call time so toggling LEXICAL_BACKEND
    # at runtime (e.g. via the system settings panel in the future)
    # takes effect without a process restart.
    backend = settings.lexical_backend
    if backend == _LEXICAL_BACKEND_MILVUS_BM25:
        lexical_fn = retrieve_lexical_milvus
    else:
        if backend not in _KNOWN_LEXICAL_BACKENDS:
            _log.warning(
                "unknown lexical_backend=%r, falling back to %r",
                backend,
                _LEXICAL_BACKEND_ILIKE,
            )
        lexical_fn = retrieve_lexical

    # P8.1: parent retriever span. Wraps dense + lexical + fusion so the
    # whole "hybrid retrieve" shows up as one OpenInference RETRIEVER
    # node in Phoenix, with per-branch counts attached as attrs (rather
    # than separate spans — these are cheap and noisy).
    with retriever_span(
        query=question,
        top_k=top_k,
        **{
            "retrieval.backend": f"hybrid({backend})",
            "tenant.id": tenant_id,
            "customer.id": customer_id,
        },
    ) as span:
        dense_hits = retrieve_dense(question, tenant_id, customer_id, top_k)
        lexical_hits = lexical_fn(question, tenant_id, customer_id, top_k)
        fused_hits = fuse_ranked_hits(
            dense_hits,
            lexical_hits,
            top_k=top_k,
            rrf_k=max(0, rag_settings.rrf_k),
            max_chunks_per_document=rag_settings.max_chunks_per_document,
        )
        final_hits = fused_hits[:top_k]
        span.set_attr("retrieval.documents.count", len(final_hits))
        span.set_attr("retrieval.dense_hits", len(dense_hits))
        span.set_attr("retrieval.lexical_hits", len(lexical_hits))
        span.set_attr("retrieval.fused_hits", len(fused_hits))
        return final_hits
