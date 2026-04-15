from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from app.services.rag.query_rewriter import rewrite_query as rewrite_query
from app.services.rag.settings import get_rag_settings
from app.services.rag.text_processing import build_search_terms, normalize_text
from app.services.rag.vector_store import get_vector_store


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

    with SessionLocal() as session:
        rows = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.id.in_(chunk_ids))
            .where(KnowledgeChunk.tenant_id == tenant_id)
            .where(KnowledgeChunk.customer_id == customer_id)
            .where(KnowledgeDocument.status == "completed")
        ).all()
    return list(rows)


def _load_chunks(tenant_id: str, customer_id: str) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
    with SessionLocal() as session:
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

    with SessionLocal() as session:
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
        fused_scores[hit.chunk_id] = fused_scores.get(hit.chunk_id, 0.0) + _reciprocal_rank(rank, rrf_k)
        merged[hit.chunk_id] = hit

    for rank, hit in enumerate(lexical_hits, start=1):
        fused_scores[hit.chunk_id] = fused_scores.get(hit.chunk_id, 0.0) + _reciprocal_rank(rank, rrf_k)
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


def retrieve_lexical(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[RetrievalHit]:
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


def retrieve_dense(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[RetrievalHit]:
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


def retrieve_hybrid(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[RetrievalHit]:
    rag_settings = get_rag_settings()
    dense_hits = retrieve_dense(question, tenant_id, customer_id, top_k)
    lexical_hits = retrieve_lexical(question, tenant_id, customer_id, top_k)
    fused_hits = fuse_ranked_hits(
        dense_hits,
        lexical_hits,
        top_k=top_k,
        rrf_k=max(0, rag_settings.rrf_k),
        max_chunks_per_document=rag_settings.max_chunks_per_document,
    )
    return fused_hits[:top_k]
