from __future__ import annotations

from dataclasses import dataclass

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument


@dataclass(frozen=True)
class CitationRecord:
    """Internal record carrying both the UI snippet and the LLM-grade full text.

    Two text fields, two callers:

    - ``snippet`` — short (≤220 chars) preview shown to the user in the
      retrieval-trace panel; truncation keeps the panel scannable.
    - ``full_content`` — the chunk's *complete* content, fed to the LLM as
      evidence. Truncating here means the model literally can't see facts
      that exist in the index, so we keep the full text.

    Both fields are populated from the same source (``chunk.content``); they
    diverge only in length.
    """

    chunk_id: str
    document_id: str
    document_title: str
    snippet: str
    full_content: str
    score: float


def build_citations(
    records: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
) -> list[CitationRecord]:
    citations: list[CitationRecord] = []
    for chunk, document, score in records:
        full_content = chunk.content.strip()
        # Snippet is the UI preview — short enough that the trace panel stays
        # readable on a single screen.
        snippet = f"{full_content[:217]}..." if len(full_content) > 220 else full_content
        bounded_score = max(0.0, min(score, 1.0))

        citations.append(
            CitationRecord(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.filename.rsplit(".", 1)[0] or document.filename,
                snippet=snippet,
                full_content=full_content,
                score=round(bounded_score, 4),
            )
        )

    return citations
