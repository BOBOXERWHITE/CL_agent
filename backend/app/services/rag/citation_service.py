from __future__ import annotations

from dataclasses import dataclass

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument


@dataclass(frozen=True)
class CitationRecord:
    chunk_id: str
    document_id: str
    document_title: str
    snippet: str
    score: float


def build_citations(records: list[tuple[KnowledgeChunk, KnowledgeDocument, float]]) -> list[CitationRecord]:
    citations: list[CitationRecord] = []
    for chunk, document, score in records:
        snippet = chunk.content.strip()
        if len(snippet) > 220:
            snippet = f"{snippet[:217]}..."
        bounded_score = max(0.0, min(score, 1.0))

        citations.append(
            CitationRecord(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.filename.rsplit(".", 1)[0] or document.filename,
                snippet=snippet,
                score=round(bounded_score, 4),
            )
        )

    return citations
