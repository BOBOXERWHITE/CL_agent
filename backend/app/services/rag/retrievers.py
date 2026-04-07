from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from app.services.rag.query_rewriter import rewrite_query
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


def retrieve_lexical(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[RetrievalHit]:
    rewritten = rewrite_query(question)
    rows = _load_chunks(tenant_id, customer_id)
    hits: list[RetrievalHit] = []

    for chunk, document in rows:
        score = lexical_overlap_score(rewritten.expanded_query, chunk.content, chunk.title)
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
    return hits[:top_k]


def retrieve_dense(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[RetrievalHit]:
    rewritten = rewrite_query(question)
    vector_hits = get_vector_store().search(
        query_text=rewritten.expanded_query,
        tenant_id=tenant_id,
        customer_id=customer_id,
        top_k=top_k,
    )
    if not vector_hits:
        return []

    chunk_ids = [chunk_id for chunk_id, _ in vector_hits]
    chunk_map = {chunk.id: (chunk, document) for chunk, document in _load_chunks(tenant_id, customer_id) if chunk.id in chunk_ids}
    hits: list[RetrievalHit] = []
    for chunk_id, dense_score in vector_hits:
        if chunk_id not in chunk_map:
            continue
        chunk, document = chunk_map[chunk_id]
        lexical_score = lexical_overlap_score(rewritten.expanded_query, chunk.content, chunk.title)
        combined_score = dense_score * 0.65 + lexical_score * 0.35
        hits.append(
            RetrievalHit(
                chunk=chunk,
                document=document,
                dense_score=dense_score,
                lexical_score=lexical_score,
                combined_score=combined_score,
            )
        )

    hits.sort(key=lambda item: item.combined_score, reverse=True)
    return hits[:top_k]


def retrieve_hybrid(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[RetrievalHit]:
    dense_hits = retrieve_dense(question, tenant_id, customer_id, max(top_k * 2, top_k))
    lexical_hits = retrieve_lexical(question, tenant_id, customer_id, max(top_k * 2, top_k))

    by_chunk: dict[str, RetrievalHit] = {}
    for hit in [*dense_hits, *lexical_hits]:
        existing = by_chunk.get(hit.chunk_id)
        if existing is None:
            by_chunk[hit.chunk_id] = hit
            continue

        combined_score = max(existing.combined_score, hit.combined_score)
        by_chunk[hit.chunk_id] = RetrievalHit(
            chunk=hit.chunk,
            document=hit.document,
            dense_score=max(existing.dense_score, hit.dense_score),
            lexical_score=max(existing.lexical_score, hit.lexical_score),
            combined_score=combined_score,
        )

    hits = list(by_chunk.values())
    hits.sort(key=lambda item: item.combined_score, reverse=True)
    return hits[:top_k]
