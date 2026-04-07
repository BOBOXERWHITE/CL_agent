from __future__ import annotations

from dataclasses import dataclass

from app.services.rag.embedding_client import text_to_embedding, texts_to_embeddings
from app.services.rag.settings import get_rag_settings


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    document_id: str
    tenant_id: str
    customer_id: str
    embedding: list[float]


def build_vector_records(chunks: list[object]) -> list[VectorRecord]:
    rag_settings = get_rag_settings()
    if not chunks:
        return []

    embeddings = texts_to_embeddings(
        [str(chunk.content) for chunk in chunks],
        rag_settings.embedding_dimension,
    )
    records: list[VectorRecord] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        records.append(
            VectorRecord(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                tenant_id=chunk.tenant_id,
                customer_id=chunk.customer_id,
                embedding=embedding,
            )
        )

    return records


__all__ = ["VectorRecord", "build_vector_records", "text_to_embedding", "texts_to_embeddings"]
