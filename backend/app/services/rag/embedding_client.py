from __future__ import annotations

import hashlib
import math
from time import perf_counter
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.services.rag.text_processing import build_search_terms


DEFAULT_SMOKE_TEST_TEXT = "北京酒店报销上限"


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
        batch_size: int = 16,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self._http_client = http_client or httpx.Client(timeout=30.0)
        self.batch_size = max(1, batch_size)
        self.max_retries = max(0, max_retries)

    def embed_texts(self, texts: list[str], dimension: int) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            embeddings.extend(self._embed_batch(batch, dimension))
        return embeddings

    def _embed_batch(self, texts: list[str], dimension: int) -> list[list[float]]:
        for attempt in range(self.max_retries + 1):
            try:
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
                return self._parse_embeddings(payload, texts, dimension)
            except httpx.HTTPStatusError as exc:
                if attempt < self.max_retries and self._is_retryable_status(exc.response.status_code):
                    continue
                raise RuntimeError(self._build_gateway_error(exc)) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    continue
                raise RuntimeError(
                    f"embedding gateway request failed for model {self.model_name} via {self.base_url}/embeddings: {exc}"
                ) from exc

        raise RuntimeError("embedding gateway request failed without a recoverable error")

    def _parse_embeddings(self, payload: dict[str, object], texts: list[str], dimension: int) -> list[list[float]]:
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        embeddings = [list(map(float, item["embedding"])) for item in data]
        if len(embeddings) != len(texts):
            raise ValueError("embedding response size mismatch")
        for embedding in embeddings:
            if len(embedding) != dimension:
                raise ValueError("embedding dimension mismatch")
        return embeddings

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 409, 429} or status_code >= 500

    def _build_gateway_error(self, exc: httpx.HTTPStatusError) -> str:
        response = exc.response
        error_message = response.text
        try:
            payload = response.json()
            error_message = payload.get("error", {}).get("message", error_message)
        except Exception:
            pass

        return (
            f"embedding gateway request failed ({response.status_code}) for model "
            f"{self.model_name} via {self.base_url}/embeddings: {error_message}"
        )


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model_name: str
    dimension: int
    profile_key: str


@dataclass(frozen=True)
class EmbeddingReadiness:
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    endpoint: str | None = None


@dataclass(frozen=True)
class EmbeddingSmokeTestResult:
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    sample_text: str
    latency_ms: float
    vector_dimension: int
    endpoint: str | None = None


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
            batch_size=settings.embedding_batch_size,
            max_retries=settings.embedding_max_retries,
        )
    return DeterministicEmbeddingClient()


def get_active_embedding_profile() -> EmbeddingProfile:
    settings = get_settings()
    if (
        settings.embedding_provider == "openai-compatible"
        and settings.embedding_api_base_url
        and settings.embedding_api_key
    ):
        return EmbeddingProfile(
            provider="openai-compatible",
            model_name=settings.embedding_model_name,
            dimension=settings.embedding_dimension,
            profile_key=(
                f"openai-compatible|{settings.embedding_model_name}|"
                f"{settings.embedding_dimension}|{settings.embedding_api_base_url}"
            ),
        )

    return EmbeddingProfile(
        provider="deterministic",
        model_name=DeterministicEmbeddingClient.model_name,
        dimension=settings.embedding_dimension,
        profile_key=f"deterministic|{DeterministicEmbeddingClient.model_name}|{settings.embedding_dimension}",
    )


def check_embedding_readiness(http_client: httpx.Client | None = None) -> EmbeddingReadiness:
    settings = get_settings()

    if settings.embedding_provider != "openai-compatible":
        return EmbeddingReadiness(
            provider="deterministic",
            model_name=DeterministicEmbeddingClient.model_name,
            configured=True,
            available=True,
            status="ready",
            message="当前使用本地 deterministic embedding，无需额外连通性检查。",
        )

    if not settings.embedding_api_base_url or not settings.embedding_api_key:
        return EmbeddingReadiness(
            provider="openai-compatible",
            model_name=settings.embedding_model_name,
            configured=False,
            available=False,
            status="missing_config",
            message="缺少 EMBEDDING_API_BASE_URL 或 EMBEDDING_API_KEY。",
            endpoint=settings.embedding_api_base_url or None,
        )

    client = http_client or httpx.Client(timeout=5.0)
    try:
        response = client.get(
            f"{settings.embedding_api_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
        )
        response.raise_for_status()
    except Exception as exc:
        return EmbeddingReadiness(
            provider="openai-compatible",
            model_name=settings.embedding_model_name,
            configured=True,
            available=False,
            status="unreachable",
            message=f"Embedding 网关不可达：{exc}",
            endpoint=settings.embedding_api_base_url,
        )

    return EmbeddingReadiness(
        provider="openai-compatible",
        model_name=settings.embedding_model_name,
        configured=True,
        available=True,
        status="ready",
        message="Embedding 网关连通正常。",
        endpoint=settings.embedding_api_base_url,
    )


def run_embedding_smoke_test(sample_text: str = DEFAULT_SMOKE_TEST_TEXT) -> EmbeddingSmokeTestResult:
    readiness = check_embedding_readiness()
    if not readiness.configured or not readiness.available:
        return EmbeddingSmokeTestResult(
            provider=readiness.provider,
            model_name=readiness.model_name,
            configured=readiness.configured,
            available=False,
            status=readiness.status,
            message=readiness.message,
            sample_text=sample_text,
            latency_ms=0.0,
            vector_dimension=0,
            endpoint=readiness.endpoint,
        )

    settings = get_settings()
    started_at = perf_counter()
    try:
        vector = text_to_embedding(sample_text, settings.embedding_dimension)
    except Exception as exc:
        return EmbeddingSmokeTestResult(
            provider=readiness.provider,
            model_name=readiness.model_name,
            configured=True,
            available=False,
            status="failed",
            message=f"Embedding 烟雾测试失败：{exc}",
            sample_text=sample_text,
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            vector_dimension=0,
            endpoint=readiness.endpoint,
        )

    return EmbeddingSmokeTestResult(
        provider=readiness.provider,
        model_name=readiness.model_name,
        configured=True,
        available=True,
        status="ready",
        message="Embedding 烟雾测试通过。",
        sample_text=sample_text,
        latency_ms=round((perf_counter() - started_at) * 1000, 2),
        vector_dimension=len(vector),
        endpoint=readiness.endpoint,
    )


def texts_to_embeddings(texts: list[str], dimension: int) -> list[list[float]]:
    return get_embedding_client().embed_texts(texts, dimension)


def text_to_embedding(text: str, dimension: int) -> list[float]:
    return texts_to_embeddings([text], dimension)[0]
