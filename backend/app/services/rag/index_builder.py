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
    # P6: full chunk text, fed to the Milvus BM25 Function (which
    # tokenizes + computes sparse BM25 weights server-side). Default
    # "" keeps existing call sites that don't yet pass content alive —
    # in that case the BM25 lexical path will simply not recall those
    # rows, which is the expected behaviour pre-migration.
    content: str = ""


def build_vector_records(chunks: list[object]) -> list[VectorRecord]:
    rag_settings = get_rag_settings()
    if not chunks:
        return []

    chunk_texts = [str(chunk.content) for chunk in chunks]
    embeddings = texts_to_embeddings(
        chunk_texts,
        rag_settings.embedding_dimension,
    )
    records: list[VectorRecord] = []
    for chunk, embedding, text in zip(chunks, embeddings, chunk_texts, strict=True):
        records.append(
            VectorRecord(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                tenant_id=chunk.tenant_id,
                customer_id=chunk.customer_id,
                embedding=embedding,
                content=text,
            )
        )

    return records


__all__ = ["VectorRecord", "build_vector_records", "text_to_embedding", "texts_to_embeddings"]
