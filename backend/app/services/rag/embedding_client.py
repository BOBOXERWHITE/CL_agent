from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass
from time import perf_counter

import httpx

from app.core.config import get_settings
from app.services.rag.text_processing import build_search_terms

DEFAULT_SMOKE_TEST_TEXT = "北京酒店报销上限"

_log = logging.getLogger(__name__)


class EmbeddingConfigError(RuntimeError):
    """Raised when the embedding client is misconfigured.

    P2.1 change: we no longer silently fall back to the deterministic
    hash embedding when ``EMBEDDING_PROVIDER=openai-compatible`` is set
    but the API base URL or key is missing. That silent fallback used to
    produce non-semantic vectors in production while looking healthy;
    now we fail fast at first use so the operator sees the problem
    immediately.
    """


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

    async def embed_texts_async(self, texts: list[str], dimension: int) -> list[list[float]]:
        """Async twin of :meth:`embed_texts`.

        The deterministic implementation is pure CPU (no IO) — we keep
        the signature async so the hot-path ``texts_to_embeddings_async``
        doesn't have to branch on which provider it got.
        """
        return self.embed_texts(texts, dimension)


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

    async def embed_texts_async(
        self,
        texts: list[str],
        dimension: int,
        *,
        async_client: httpx.AsyncClient | None = None,
    ) -> list[list[float]]:
        """Async twin of :meth:`embed_texts` (P4.1).

        Identical batching + retry semantics, but every HTTP call is
        ``await``-ed so concurrent requests on the same FastAPI worker
        don't serialise the event loop. ``async_client`` is injectable
        for tests; production callers leave it ``None`` and pick up the
        shared client from ``app.services.rag.async_http_client``.
        """
        if not texts:
            return []

        client = async_client
        if client is None:
            from app.services.rag.async_http_client import get_async_http_client

            client = get_async_http_client()

        embeddings: list[list[float]] = []
        effective_batch_size = self._get_effective_batch_size()
        for start in range(0, len(texts), effective_batch_size):
            batch = texts[start : start + effective_batch_size]
            embeddings.extend(await self._embed_batch_async(batch, dimension, client))
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
                if attempt < self.max_retries and self._is_retryable_status(
                    exc.response.status_code
                ):
                    continue
                raise RuntimeError(self._build_gateway_error(exc)) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    continue
                raise RuntimeError(
                    f"embedding gateway request failed for model {self.model_name} via {self.base_url}/embeddings: {exc}"
                ) from exc

        raise RuntimeError("embedding gateway request failed without a recoverable error")

    def _parse_embeddings(
        self, payload: dict[str, object], texts: list[str], dimension: int
    ) -> list[list[float]]:
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        embeddings = [list(map(float, item["embedding"])) for item in data]
        if len(embeddings) != len(texts):
            raise ValueError("embedding response size mismatch")
        for embedding in embeddings:
            if len(embedding) != dimension:
                raise ValueError("embedding dimension mismatch")
        return embeddings

    async def _embed_batch_async(
        self,
        texts: list[str],
        dimension: int,
        client: httpx.AsyncClient,
    ) -> list[list[float]]:
        """Async version of :meth:`_embed_batch`.

        Retry ladder mirrors the sync path: N retries, exponential
        ``asyncio.sleep`` backoff instead of the sync's tight loop.
        Keeping the two paths behaviourally identical is the whole
        point — worker and FastAPI route should see the same outcome
        for the same failure.
        """
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.post(
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
                if attempt < self.max_retries and self._is_retryable_status(
                    exc.response.status_code
                ):
                    await asyncio.sleep(2**attempt * 0.1)
                    continue
                raise RuntimeError(self._build_gateway_error(exc)) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(2**attempt * 0.1)
                    continue
                raise RuntimeError(
                    f"embedding gateway request failed for model {self.model_name} via {self.base_url}/embeddings: {exc}"
                ) from exc

        raise RuntimeError("embedding gateway request failed without a recoverable error")

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
        request_dimensions
        if request_dimensions is not None
        else settings.embedding_request_dimensions,
        (
            encoding_format if encoding_format is not None else settings.embedding_encoding_format
        ).strip()
        or None,
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
    """Return the configured embedding client or raise if misconfigured.

    Provider matrix:

    +-------------------------+------------------------------------------+
    | EMBEDDING_PROVIDER      | Behaviour                                |
    +=========================+==========================================+
    | deterministic (default) | Hash-BoW local client. Only meaningful   |
    |                         | for unit tests; produces non-semantic    |
    |                         | vectors, so retrieval is near-random.    |
    +-------------------------+------------------------------------------+
    | openai-compatible       | HTTP client against any /v1/embeddings   |
    |                         | endpoint. Requires EMBEDDING_API_BASE_URL|
    |                         | AND EMBEDDING_API_KEY; missing either    |
    |                         | raises EmbeddingConfigError rather than  |
    |                         | falling back silently (P2.1 change).     |
    +-------------------------+------------------------------------------+

    The previous silent-fallback behaviour is preserved only when the
    provider is left at ``deterministic``; explicit ``openai-compatible``
    is treated as a hard commitment.
    """
    settings = get_settings()
    provider = settings.embedding_provider.strip().lower()
    if provider == "openai-compatible":
        missing: list[str] = []
        if not settings.embedding_api_base_url:
            missing.append("EMBEDDING_API_BASE_URL")
        if not settings.embedding_api_key:
            missing.append("EMBEDDING_API_KEY")
        if missing:
            raise EmbeddingConfigError(
                "EMBEDDING_PROVIDER=openai-compatible but required config is missing: "
                + ", ".join(missing)
                + ". Set these env vars or switch EMBEDDING_PROVIDER=deterministic "
                "(tests only). See backend/.env.example for the full template."
            )
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
        encoding_part = (
            f"|encoding={settings.embedding_encoding_format}"
            if settings.embedding_encoding_format
            else ""
        )
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
    """Embed ``texts`` with a best-effort cache read / write (P2.7 接入).

    Per-text cache: key = ``emb:{model}:{sha256(text)[:32]}``. Missing
    entries are computed by the provider in one batched call; the whole
    batch is written back. Cache misses are treated as slow paths, not
    errors -- any cache exception degrades to "no cache for this call".

    The model name is part of the key so rotating ``EMBEDDING_MODEL_NAME``
    (e.g. text-embedding-3-small → bge-m3) does not serve stale vectors.

    P8.1: wraps the whole operation in an OpenInference ``embedding``
    span so Phoenix shows latency + batch size + cache hit ratio per call.
    Cache-only paths still emit a span (with ``cache.miss=0``) so dashboard
    "embedding QPS" charts don't undercount cached requests.
    """
    if not texts:
        return []

    from app.core.cache import embedding_cache_key, get_cache
    from app.core.observability.agent_tracing import embedding_span

    profile = get_active_embedding_profile()
    cache = get_cache()
    settings = get_settings()

    with embedding_span(
        model_name=profile.model_name,
        provider=profile.provider,
        text_count=len(texts),
        dimension=dimension,
    ) as span:
        keys: list[str] = [embedding_cache_key(profile.model_name, t) for t in texts]
        cached: list[list[float] | None] = []
        miss_indices: list[int] = []
        for idx, key in enumerate(keys):
            try:
                hit = cache.get(key)
            except Exception:
                hit = None
            if (
                isinstance(hit, list)
                and len(hit) == dimension
                and all(isinstance(v, int | float) for v in hit)
            ):
                cached.append([float(v) for v in hit])
            else:
                cached.append(None)
                miss_indices.append(idx)

        if miss_indices:
            miss_texts = [texts[i] for i in miss_indices]
            fresh = get_embedding_client().embed_texts(miss_texts, dimension)
            for slot, vector in zip(miss_indices, fresh, strict=True):
                cached[slot] = vector
                try:
                    cache.set(keys[slot], vector, ttl_seconds=settings.cache_embedding_ttl_seconds)
                except Exception:
                    pass

        # Per-call cache observability so the embedding cost chart in
        # Phoenix is meaningful (a 100 % cache-hit call = $0 + ~0 ms).
        span.set_attr("embedding.cache.hits", len(texts) - len(miss_indices))
        span.set_attr("embedding.cache.misses", len(miss_indices))

        # Every slot is filled by this point (either cache hit or fresh result).
        return [vector for vector in cached if vector is not None]


def text_to_embedding(text: str, dimension: int) -> list[float]:
    return texts_to_embeddings([text], dimension)[0]


async def texts_to_embeddings_async(texts: list[str], dimension: int) -> list[list[float]]:
    """Async twin of :func:`texts_to_embeddings` (P4.1).

    Cache semantics are identical — hits are read synchronously (Redis
    client in this codebase is sync, which is fine: ``cache.get`` is
    microseconds), misses are batched and embedded via the provider's
    async API. Only the network IO is awaited; the surrounding glue is
    unchanged so behaviour matches the sync helper byte-for-byte.

    P8.1: matches the sync helper's ``embedding`` span behaviour.
    """
    if not texts:
        return []

    from app.core.cache import embedding_cache_key, get_cache
    from app.core.observability.agent_tracing import embedding_span

    profile = get_active_embedding_profile()
    cache = get_cache()
    settings = get_settings()

    with embedding_span(
        model_name=profile.model_name,
        provider=profile.provider,
        text_count=len(texts),
        dimension=dimension,
    ) as span:
        keys: list[str] = [embedding_cache_key(profile.model_name, t) for t in texts]
        cached: list[list[float] | None] = []
        miss_indices: list[int] = []
        for idx, key in enumerate(keys):
            try:
                hit = cache.get(key)
            except Exception:
                hit = None
            if (
                isinstance(hit, list)
                and len(hit) == dimension
                and all(isinstance(v, int | float) for v in hit)
            ):
                cached.append([float(v) for v in hit])
            else:
                cached.append(None)
                miss_indices.append(idx)

        if miss_indices:
            miss_texts = [texts[i] for i in miss_indices]
            client = get_embedding_client()
            fresh = await client.embed_texts_async(miss_texts, dimension)
            for slot, vector in zip(miss_indices, fresh, strict=True):
                cached[slot] = vector
                try:
                    cache.set(keys[slot], vector, ttl_seconds=settings.cache_embedding_ttl_seconds)
                except Exception:
                    pass

        span.set_attr("embedding.cache.hits", len(texts) - len(miss_indices))
        span.set_attr("embedding.cache.misses", len(miss_indices))

        return [vector for vector in cached if vector is not None]


async def text_to_embedding_async(text: str, dimension: int) -> list[float]:
    """Async single-text convenience; delegates to :func:`texts_to_embeddings_async`."""
    vectors = await texts_to_embeddings_async([text], dimension)
    return vectors[0]
