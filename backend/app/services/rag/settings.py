from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class RagSettings:
    chunk_size: int
    chunk_overlap: int
    embedding_dimension: int
    milvus_collection_name: str
    dense_candidate_multiplier: int
    lexical_candidate_multiplier: int
    rrf_k: int
    max_chunks_per_document: int


def get_rag_settings() -> RagSettings:
    settings = get_settings()
    return RagSettings(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        embedding_dimension=settings.embedding_dimension,
        milvus_collection_name=settings.milvus_collection_name,
        dense_candidate_multiplier=settings.rag_dense_candidate_multiplier,
        lexical_candidate_multiplier=settings.rag_lexical_candidate_multiplier,
        rrf_k=settings.rag_rrf_k,
        max_chunks_per_document=settings.rag_max_chunks_per_document,
    )
