"""Cache abstraction with Redis + in-memory + noop backends.

Public API is the ``Cache`` protocol: ``get(key)`` / ``set(key, value,
ttl)`` / ``delete(key)`` / ``clear_prefix(prefix)``. Backends:

- ``NoopCache``: always misses; ``set`` is a no-op. Used when
  ``CACHE_ENABLED=false`` so callers don't need ``if cache:`` guards.
- ``InMemoryCache``: dict + TTL tracking, single process. Used in unit
  tests so we don't require a Redis container for cache-behaviour tests.
- ``RedisCache``: redis-py client; used in dev/prod when CACHE_ENABLED.

Value encoding is JSON, which covers dicts / lists / primitives. If a
caller stores something non-JSON-serialisable the cache raises on
``set``; we don't silently drop.

Keys are namespaced via module-level helpers so callers use short,
consistent names:
- embedding_cache_key(model, text)
- retrieval_cache_key(tenant, query_signature)
- answer_cache_key(tenant, query_signature, top_chunks_signature)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import Settings, get_settings

_log = logging.getLogger(__name__)


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...

    def clear_prefix(self, prefix: str) -> int: ...


class NoopCache:
    """Always miss; ``set`` is a no-op. Safe default."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        return None

    def delete(self, key: str) -> None:
        return None

    def clear_prefix(self, prefix: str) -> int:
        return 0


@dataclass
class _Entry:
    value: Any
    expires_at: float | None  # monotonic


@dataclass
class InMemoryCache:
    """Process-local dict cache with TTL. Suitable for tests and single-worker dev."""

    _store: dict[str, _Entry] = field(default_factory=dict)

    def _expired(self, entry: _Entry) -> bool:
        return entry.expires_at is not None and entry.expires_at <= time.monotonic()

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if self._expired(entry):
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        # JSON-roundtrip to surface non-serialisable values early.
        json.dumps(value)
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        self._store[key] = _Entry(value=value, expires_at=expires_at)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear_prefix(self, prefix: str) -> int:
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)


class RedisCache:
    """Redis-backed cache. JSON-encoded values; short binary keys."""

    def __init__(self, url: str) -> None:
        import redis  # local import so the module stays import-safe without redis

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            _log.warning("cache_redis_decode_failed", extra={"key": key})
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        if ttl_seconds and ttl_seconds > 0:
            self._client.set(key, payload, ex=ttl_seconds)
        else:
            self._client.set(key, payload)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def clear_prefix(self, prefix: str) -> int:
        """Scan and delete matching keys. Uses SCAN to avoid blocking Redis."""
        pattern = f"{prefix}*"
        removed = 0
        for key in self._client.scan_iter(match=pattern, count=500):
            self._client.delete(key)
            removed += 1
        return removed


_cache_singleton: Cache | None = None


def _build_cache(settings: Settings) -> Cache:
    if not settings.cache_enabled:
        return NoopCache()
    try:
        return RedisCache(settings.cache_redis_url)
    except Exception as exc:
        _log.warning(
            "cache_redis_unavailable_falling_back_to_noop",
            extra={"error": str(exc), "url": settings.cache_redis_url},
        )
        return NoopCache()


def get_cache() -> Cache:
    """Return the process-wide cache. Cached after first build so tests
    can reset via ``reset_cache()``.
    """
    global _cache_singleton
    if _cache_singleton is None:
        _cache_singleton = _build_cache(get_settings())
    return _cache_singleton


def reset_cache() -> None:
    """Drop the cached singleton. Tests call this between fixtures."""
    global _cache_singleton
    _cache_singleton = None


def set_cache(cache: Cache) -> None:
    """Inject a specific backend (tests, future DI)."""
    global _cache_singleton
    _cache_singleton = cache


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def embedding_cache_key(model: str, text: str) -> str:
    return f"emb:{model}:{_hash(text)}"


def retrieval_cache_key(tenant_id: str, query_signature: str) -> str:
    return f"retr:{tenant_id}:{_hash(query_signature)}"


def answer_cache_key(tenant_id: str, query_signature: str, top_chunks_signature: str) -> str:
    return f"ans:{tenant_id}:{_hash(query_signature + '|' + top_chunks_signature)}"


__all__ = [
    "Cache",
    "InMemoryCache",
    "NoopCache",
    "RedisCache",
    "answer_cache_key",
    "embedding_cache_key",
    "get_cache",
    "reset_cache",
    "retrieval_cache_key",
    "set_cache",
]
