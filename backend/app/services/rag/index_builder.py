from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

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
    records: list[VectorRecord] = []

    for chunk in chunks:
        records.append(
            VectorRecord(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                tenant_id=chunk.tenant_id,
                customer_id=chunk.customer_id,
                embedding=text_to_embedding(chunk.content, rag_settings.embedding_dimension),
            )
        )

    return records


def text_to_embedding(text: str, dimension: int) -> list[float]:
    if dimension <= 0:
        raise ValueError("embedding dimension must be positive")

    vector = [0.0] * dimension
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        vector[bucket] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
