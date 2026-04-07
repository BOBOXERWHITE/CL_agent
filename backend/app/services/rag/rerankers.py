from __future__ import annotations

from app.services.rag.retrievers import RetrievalHit, lexical_overlap_score
from app.services.rag.text_processing import normalize_text


def rerank_hits(question: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
    normalized_question = normalize_text(question)
    reranked: list[RetrievalHit] = []

    for hit in hits:
        phrase_bonus = 0.0
        normalized_content = normalize_text(hit.chunk.content)
        if normalized_question and normalized_question in normalized_content:
            phrase_bonus += 0.4
        lexical_bonus = lexical_overlap_score(question, hit.chunk.content, hit.chunk.title) * 0.15
        final_score = hit.combined_score + phrase_bonus + lexical_bonus
        reranked.append(
            RetrievalHit(
                chunk=hit.chunk,
                document=hit.document,
                dense_score=hit.dense_score,
                lexical_score=hit.lexical_score,
                combined_score=final_score,
            )
        )

    reranked.sort(key=lambda item: item.combined_score, reverse=True)
    return reranked[:top_k]
