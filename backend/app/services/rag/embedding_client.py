from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from time import perf_counter

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
        request_dimensions: int | None = None,
        encoding_format: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self._http_client = http_client or httpx.Client(timeout=30.0)
        self.batch_size = max(1, batch_size)
        self.max_retries = max(0, max_retries)
        self.request_dimensions = request_dimensions
        self.encoding_format = (encoding_format or "").strip() or None

    def embed_texts(self, texts: list[str], dimension: int) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        effective_batch_size = self._get_effective_batch_size()
        for start in range(0, len(texts), effective_batch_size):
            batch = texts[start : start + effective_batch_size]
            embeddings.extend(self._embed_batch(batch, dimension))
        return embeddings

    def _get_effective_batch_size(self) -> int:
        if "dashscope.aliyuncs.com" in self.base_url.lower():
            return min(self.batch_size, 10)
        return self.batch_size

    def _build_request_payload(self, texts: list[str]) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model_name,
            "input": texts,
        }
        if self.request_dimensions is not None:
            payload["dimensions"] = self.request_dimensions
        if self.encoding_format:
            payload["encoding_format"] = self.encoding_format
        return payload

    def _embed_batch(self, texts: list[str], dimension: int) -> list[list[float]]:
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http_client.post(
                    f"{self.base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._build_request_payload(texts),
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


def _resolve_embedding_gateway_settings(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    dimension: int | None = None,
    request_dimensions: int | None = None,
    encoding_format: str | None = None,
) -> tuple[str, str, str, str, int, int | None, str | None]:
    settings = get_settings()
    return (
        (provider or settings.embedding_provider).strip().lower(),
        (base_url or settings.embedding_api_base_url).strip(),
        (api_key or settings.embedding_api_key).strip(),
        (model_name or settings.embedding_model_name).strip(),
        dimension or settings.embedding_dimension,
        request_dimensions if request_dimensions is not None else settings.embedding_request_dimensions,
        (encoding_format if encoding_format is not None else settings.embedding_encoding_format).strip() or None,
    )


def _supports_models_endpoint(status_code: int) -> bool:
    return status_code not in {404, 405, 501}


def _probe_embedding_endpoint(
    *,
    base_url: str,
    api_key: str,
    model_name: str,
    dimension: int,
    request_dimensions: int | None,
    encoding_format: str | None,
    http_client: httpx.Client,
) -> None:
    client = OpenAICompatibleEmbeddingClient(
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        http_client=http_client,
        request_dimensions=request_dimensions,
        encoding_format=encoding_format,
    )
    client.embed_texts([DEFAULT_SMOKE_TEST_TEXT], dimension)


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
            request_dimensions=settings.embedding_request_dimensions,
            encoding_format=settings.embedding_encoding_format,
        )
    return DeterministicEmbeddingClient()


def get_active_embedding_profile() -> EmbeddingProfile:
    settings = get_settings()
    if (
        settings.embedding_provider == "openai-compatible"
        and settings.embedding_api_base_url
        and settings.embedding_api_key
    ):
        request_dimension_part = (
            f"|request_dim={settings.embedding_request_dimensions}"
            if settings.embedding_request_dimensions is not None
            else ""
        )
        encoding_part = f"|encoding={settings.embedding_encoding_format}" if settings.embedding_encoding_format else ""
        return EmbeddingProfile(
            provider="openai-compatible",
            model_name=settings.embedding_model_name,
            dimension=settings.embedding_dimension,
            profile_key=(
                f"openai-compatible|{settings.embedding_model_name}|"
                f"{settings.embedding_dimension}|{settings.embedding_api_base_url}"
                f"{request_dimension_part}{encoding_part}"
            ),
        )

    return EmbeddingProfile(
        provider="deterministic",
        model_name=DeterministicEmbeddingClient.model_name,
        dimension=settings.embedding_dimension,
        profile_key=f"deterministic|{DeterministicEmbeddingClient.model_name}|{settings.embedding_dimension}",
    )


def check_embedding_readiness(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    dimension: int | None = None,
    request_dimensions: int | None = None,
    encoding_format: str | None = None,
    http_client: httpx.Client | None = None,
) -> EmbeddingReadiness:
    (
        resolved_provider,
        resolved_base_url,
        resolved_api_key,
        resolved_model_name,
        resolved_dimension,
        resolved_request_dimensions,
        resolved_encoding_format,
    ) = _resolve_embedding_gateway_settings(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        dimension=dimension,
        request_dimensions=request_dimensions,
        encoding_format=encoding_format,
    )

    if resolved_provider != "openai-compatible":
        return EmbeddingReadiness(
            provider="deterministic",
            model_name=DeterministicEmbeddingClient.model_name,
            configured=True,
            available=True,
            status="ready",
            message="当前使用本地 deterministic embedding，无需额外连通性检查。",
        )

    if not resolved_base_url or not resolved_api_key:
        return EmbeddingReadiness(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=False,
            available=False,
            status="missing_config",
            message="缺少 EMBEDDING_API_BASE_URL 或 EMBEDDING_API_KEY。",
            endpoint=resolved_base_url or None,
        )

    client = http_client or httpx.Client(timeout=5.0)
    try:
        response = client.get(
            f"{resolved_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {resolved_api_key}"},
        )
        response.raise_for_status()
        payload = response.json()
        model_ids = [
            str(item.get("id"))
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    except httpx.HTTPStatusError as exc:
        if _supports_models_endpoint(exc.response.status_code):
            return EmbeddingReadiness(
                provider="openai-compatible",
                model_name=resolved_model_name,
                configured=True,
                available=False,
                status="unreachable",
                message=f"Embedding 网关不可达：{exc}",
                endpoint=resolved_base_url,
            )

        try:
            _probe_embedding_endpoint(
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                model_name=resolved_model_name,
                dimension=resolved_dimension,
                request_dimensions=resolved_request_dimensions,
                encoding_format=resolved_encoding_format,
                http_client=client,
            )
        except Exception as probe_exc:
            return EmbeddingReadiness(
                provider="openai-compatible",
                model_name=resolved_model_name,
                configured=True,
                available=False,
                status="unreachable",
                message=f"Embedding 网关不可达：/models 不可用，且真实向量探活失败：{probe_exc}",
                endpoint=resolved_base_url,
            )

        return EmbeddingReadiness(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=True,
            available=True,
            status="ready",
            message=f"Embedding 网关连通正常；/models 不可用，已通过真实向量探活验证 {resolved_model_name}。",
            endpoint=resolved_base_url,
        )
    except Exception as exc:
        return EmbeddingReadiness(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=True,
            available=False,
            status="unreachable",
            message=f"Embedding 网关不可达：{exc}",
            endpoint=resolved_base_url,
        )

    model_hint = (
        f"；当前模型 {resolved_model_name} 已在网关列表中。"
        if resolved_model_name in model_ids
        else f"；当前模型 {resolved_model_name} 未在网关列表中显式返回。"
    )
    return EmbeddingReadiness(
        provider="openai-compatible",
        model_name=resolved_model_name,
        configured=True,
        available=True,
        status="ready",
        message=f"Embedding 网关连通正常{model_hint}",
        endpoint=resolved_base_url,
    )


def run_embedding_smoke_test(
    sample_text: str = DEFAULT_SMOKE_TEST_TEXT,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    dimension: int | None = None,
    request_dimensions: int | None = None,
    encoding_format: str | None = None,
    http_client: httpx.Client | None = None,
) -> EmbeddingSmokeTestResult:
    (
        resolved_provider,
        resolved_base_url,
        resolved_api_key,
        resolved_model_name,
        resolved_dimension,
        resolved_request_dimensions,
        resolved_encoding_format,
    ) = _resolve_embedding_gateway_settings(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        dimension=dimension,
        request_dimensions=request_dimensions,
        encoding_format=encoding_format,
    )

    if resolved_provider != "openai-compatible":
        started_at = perf_counter()
        vector = text_to_embedding(sample_text, resolved_dimension)
        return EmbeddingSmokeTestResult(
            provider="deterministic",
            model_name=DeterministicEmbeddingClient.model_name,
            configured=True,
            available=True,
            status="ready",
            message="Embedding 烟雾测试通过。",
            sample_text=sample_text,
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            vector_dimension=len(vector),
            endpoint=None,
        )

    if not resolved_base_url or not resolved_api_key:
        return EmbeddingSmokeTestResult(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=False,
            available=False,
            status="missing_config",
            message="缺少 EMBEDDING_API_BASE_URL 或 EMBEDDING_API_KEY。",
            sample_text=sample_text,
            latency_ms=0.0,
            vector_dimension=0,
            endpoint=resolved_base_url or None,
        )

    client = OpenAICompatibleEmbeddingClient(
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        model_name=resolved_model_name,
        http_client=http_client,
        batch_size=get_settings().embedding_batch_size,
        max_retries=get_settings().embedding_max_retries,
        request_dimensions=resolved_request_dimensions,
        encoding_format=resolved_encoding_format,
    )
    started_at = perf_counter()
    try:
        vector = client.embed_texts([sample_text], resolved_dimension)[0]
    except Exception as exc:
        return EmbeddingSmokeTestResult(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=True,
            available=False,
            status="failed",
            message=f"Embedding 烟雾测试失败：{exc}",
            sample_text=sample_text,
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            vector_dimension=0,
            endpoint=resolved_base_url,
        )

    return EmbeddingSmokeTestResult(
        provider="openai-compatible",
        model_name=resolved_model_name,
        configured=True,
        available=True,
        status="ready",
        message="Embedding 烟雾测试通过。",
        sample_text=sample_text,
        latency_ms=round((perf_counter() - started_at) * 1000, 2),
        vector_dimension=len(vector),
        endpoint=resolved_base_url,
    )


def texts_to_embeddings(texts: list[str], dimension: int) -> list[list[float]]:
    return get_embedding_client().embed_texts(texts, dimension)


def text_to_embedding(text: str, dimension: int) -> list[float]:
    return texts_to_embeddings([text], dimension)[0]
