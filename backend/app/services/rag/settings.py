from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class RagSettings:
    chunk_size: int
    chunk_overlap: int
    embedding_dimension: int
    milvus_collection_name: str


def get_rag_settings() -> RagSettings:
    settings = get_settings()
    return RagSettings(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        embedding_dimension=settings.embedding_dimension,
        milvus_collection_name=settings.milvus_collection_name,
    )
