from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Iterable

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal, init_db
from app.services.llm.client import get_policy_answer_client
from app.services.prompts.service import PromptSelection, get_prompt_selection
from app.services.rag.citation_service import CitationRecord, build_citations
from app.services.rag.query_rewriter import rewrite_query
from app.services.rag.rerankers import rerank_hits
from app.services.rag.retrievers import RetrievalHit, retrieve_dense, retrieve_lexical
from app.services.rag.text_processing import extract_cjk_sequences


@dataclass(frozen=True)
class PolicyAnswerResult:
    answer: str
    confidence: float
    citations: list[CitationRecord]
    retrieval_trace: "RetrievalTrace"
    prompt_template_id: str | None


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
        }


def _is_chinese_query(question: str) -> bool:
    return bool(extract_cjk_sequences(question))


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
    return [
        (hit.chunk, hit.document, hit.combined_score)
        for hit in retrieve_lexical(question, tenant_id, customer_id, top_k)
    ]


def _vector_search(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    return [
        (hit.chunk, hit.document, hit.combined_score)
        for hit in retrieve_dense(question, tenant_id, customer_id, top_k)
    ]


def _to_hit_records(records: list[tuple[KnowledgeChunk, KnowledgeDocument, float]]) -> list[RetrievalHit]:
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


def _hybrid_search(question: str, tenant_id: str, customer_id: str, top_k: int) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    dense_records = _vector_search(question, tenant_id, customer_id, max(top_k * 2, top_k))
    lexical_records = _lexical_search(question, tenant_id, customer_id, max(top_k * 2, top_k))

    merged: dict[str, RetrievalHit] = {}
    for hit in [*_to_hit_records(dense_records), *_to_hit_records(lexical_records)]:
        existing = merged.get(hit.chunk.id)
        if existing is None or hit.combined_score > existing.combined_score:
            merged[hit.chunk.id] = hit

    reranked = rerank_hits(question, list(merged.values()), top_k)
    return [(hit.chunk, hit.document, hit.combined_score) for hit in reranked]


def _build_trace(
    *,
    retrieval_mode: str,
    prompt_selection: PromptSelection,
    citations: list[CitationRecord],
    model_name: str,
    token_usage: dict[str, int],
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
    )


def answer_policy_question(question: str, tenant_id: str, customer_id: str) -> PolicyAnswerResult:
    init_db()
    settings = get_settings()
    answer_client = get_policy_answer_client()
    client_model_name = getattr(answer_client, "model_name", settings.llm_model_name)
    with SessionLocal() as session:
        prompt_selection = get_prompt_selection(session, "policy_answer")

    rewritten_query = rewrite_query(question)
    retrieval_started_at = perf_counter()
    retrieval_mode = "hybrid"
    retrievals = _hybrid_search(rewritten_query.expanded_query, tenant_id, customer_id, settings.chat_top_k)
    if not retrievals:
        retrieval_mode = "vector"
        retrievals = _vector_search(rewritten_query.expanded_query, tenant_id, customer_id, settings.chat_top_k)
    if not retrievals:
        retrieval_mode = "lexical"
        retrievals = _lexical_search(rewritten_query.expanded_query, tenant_id, customer_id, settings.chat_top_k)
    retrieval_elapsed_ms = int((perf_counter() - retrieval_started_at) * 1000)

    citations = build_citations(retrievals)
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
    if top_score < settings.chat_confidence_threshold:
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
        )
        return PolicyAnswerResult(
            answer=low_confidence_answer,
            confidence=round(top_score, 4),
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
    retrieval_trace = _build_trace(
        retrieval_mode=f"{retrieval_mode}:{retrieval_elapsed_ms}ms/{generation_elapsed_ms}ms",
        prompt_selection=prompt_selection,
        citations=citations,
        model_name=answer_draft.model_name,
        token_usage=answer_draft.token_usage,
    )
    return PolicyAnswerResult(
        answer=answer_draft.answer,
        confidence=round(answer_draft.confidence, 4),
        citations=citations,
        retrieval_trace=retrieval_trace,
        prompt_template_id=prompt_selection.id,
    )
