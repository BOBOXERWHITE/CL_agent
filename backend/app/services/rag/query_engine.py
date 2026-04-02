from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal, init_db
from app.services.llm.client import get_policy_answer_client
from app.services.rag.citation_service import CitationRecord, build_citations
from app.services.rag.index_builder import text_to_embedding
from app.services.rag.vector_store import get_vector_store


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")


@dataclass(frozen=True)
class PolicyAnswerResult:
    answer: str
    confidence: float
    citations: list[CitationRecord]


def tokenize_text(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def lexical_overlap_score(query: str, content: str, title: str) -> float:
    query_tokens = set(tokenize_text(query))
    if not query_tokens:
        return 0.0

    content_tokens = set(tokenize_text(content))
    title_tokens = set(tokenize_text(title))
    overlap = len(query_tokens & content_tokens)
    title_overlap = len(query_tokens & title_tokens)
    return overlap / len(query_tokens) + title_overlap * 0.15


def _load_chunk_map(chunk_ids: Iterable[str]) -> dict[str, tuple[KnowledgeChunk, KnowledgeDocument]]:
    chunk_ids = list(chunk_ids)
    if not chunk_ids:
        return {}

    with SessionLocal() as session:
        rows = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.id.in_(chunk_ids))
        ).all()

    return {chunk.id: (chunk, document) for chunk, document in rows}


def _lexical_search(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.tenant_id == tenant_id)
            .where(KnowledgeChunk.customer_id == customer_id)
            .where(KnowledgeDocument.status == "completed")
        ).all()

    scored: list[tuple[KnowledgeChunk, KnowledgeDocument, float]] = []
    for chunk, document in rows:
        score = lexical_overlap_score(question, chunk.content, chunk.title)
        if score > 0:
            scored.append((chunk, document, score))

    scored.sort(key=lambda item: item[2], reverse=True)
    return scored[:top_k]


def _vector_search(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    vector_hits = get_vector_store().search(
        query_text=question,
        tenant_id=tenant_id,
        customer_id=customer_id,
        top_k=top_k,
    )
    chunk_map = _load_chunk_map([chunk_id for chunk_id, _ in vector_hits])

    results: list[tuple[KnowledgeChunk, KnowledgeDocument, float]] = []
    for chunk_id, score in vector_hits:
        if chunk_id not in chunk_map:
            continue
        chunk, document = chunk_map[chunk_id]
        lexical = lexical_overlap_score(question, chunk.content, chunk.title)
        results.append((chunk, document, max(score, lexical)))

    results.sort(key=lambda item: item[2], reverse=True)
    return results[:top_k]


def answer_policy_question(question: str, tenant_id: str, customer_id: str) -> PolicyAnswerResult:
    init_db()
    settings = get_settings()

    retrievals = _vector_search(question, tenant_id, customer_id, settings.chat_top_k)
    if not retrievals:
        retrievals = _lexical_search(question, tenant_id, customer_id, settings.chat_top_k)

    citations = build_citations(retrievals)
    if not citations:
        return PolicyAnswerResult(
            answer="I do not have enough policy evidence to answer this question confidently yet.",
            confidence=0.0,
            citations=[],
        )

    evidence_snippets = [citation.snippet for citation in citations]
    top_score = max(0.0, min(citations[0].score, 1.0))
    if top_score < settings.chat_confidence_threshold:
        return PolicyAnswerResult(
            answer="I found related policy text, but the evidence is not strong enough for a confident answer yet.",
            confidence=round(top_score, 4),
            citations=citations,
        )

    answer_draft = get_policy_answer_client().generate_answer(
        question=question,
        evidence_snippets=evidence_snippets,
        confidence=top_score,
    )
    return PolicyAnswerResult(
        answer=answer_draft.answer,
        confidence=round(answer_draft.confidence, 4),
        citations=citations,
    )
