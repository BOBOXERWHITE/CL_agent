from __future__ import annotations

import hashlib
import math

import httpx

from app.core.config import get_settings
from app.services.rag.text_processing import build_search_terms


def _deterministic_embedding(text: str, dimension: int) -> list[float]:
    if dimension <= 0:
        raise ValueError("embedding dimension must be positive")

    vector = [0.0] * dimension
    tokens = build_search_terms(text)
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


class DeterministicEmbeddingClient:
    model_name = "deterministic-hash-embedding"

    def embed_texts(self, texts: list[str], dimension: int) -> list[list[float]]:
        return [_deterministic_embedding(text, dimension) for text in texts]


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self._http_client = http_client or httpx.Client(timeout=30.0)

    def embed_texts(self, texts: list[str], dimension: int) -> list[list[float]]:
        response = self._http_client.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "input": texts,
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        embeddings = [list(map(float, item["embedding"])) for item in data]
        if len(embeddings) != len(texts):
            raise ValueError("embedding response size mismatch")
        for embedding in embeddings:
            if len(embedding) != dimension:
                raise ValueError("embedding dimension mismatch")
        return embeddings


def get_embedding_client() -> DeterministicEmbeddingClient | OpenAICompatibleEmbeddingClient:
    settings = get_settings()
    if (
        settings.embedding_provider == "openai-compatible"
        and settings.embedding_api_base_url
        and settings.embedding_api_key
    ):
        return OpenAICompatibleEmbeddingClient(
            base_url=settings.embedding_api_base_url,
            api_key=settings.embedding_api_key,
            model_name=settings.embedding_model_name,
        )
    return DeterministicEmbeddingClient()


def texts_to_embeddings(texts: list[str], dimension: int) -> list[list[float]]:
    return get_embedding_client().embed_texts(texts, dimension)


def text_to_embedding(text: str, dimension: int) -> list[float]:
    return texts_to_embeddings([text], dimension)[0]
