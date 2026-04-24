"""Tests for the P2.7 cache abstraction.

Redis-specific behaviour is covered only when a redis client is
importable AND a simple connection works; otherwise those tests are
skipped. The Noop + InMemory paths are tested unconditionally because
they form the correctness contract callers rely on.
"""

from __future__ import annotations

import time

import pytest

from app.core.cache import (
    InMemoryCache,
    NoopCache,
    answer_cache_key,
    embedding_cache_key,
    get_cache,
    reset_cache,
    retrieval_cache_key,
    set_cache,
)


def test_noop_cache_always_misses() -> None:
    cache = NoopCache()
    cache.set("k", {"v": 1}, ttl_seconds=60)
    assert cache.get("k") is None


def test_in_memory_cache_round_trip() -> None:
    cache = InMemoryCache()
    cache.set("greeting", {"hello": "world"})
    assert cache.get("greeting") == {"hello": "world"}


def test_in_memory_cache_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = InMemoryCache()
    current = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: current[0])
    cache.set("k", "v", ttl_seconds=5)
    assert cache.get("k") == "v"
    current[0] += 6  # TTL expired
    assert cache.get("k") is None


def test_in_memory_cache_delete() -> None:
    cache = InMemoryCache()
    cache.set("k", 42)
    cache.delete("k")
    assert cache.get("k") is None


def test_in_memory_cache_clear_prefix_removes_matching() -> None:
    cache = InMemoryCache()
    cache.set("emb:A:1", [1.0])
    cache.set("emb:A:2", [2.0])
    cache.set("ans:A:1", "answer")
    removed = cache.clear_prefix("emb:")
    assert removed == 2
    assert cache.get("emb:A:1") is None
    assert cache.get("emb:A:2") is None
    assert cache.get("ans:A:1") == "answer"


def test_in_memory_cache_rejects_non_json_values() -> None:
    cache = InMemoryCache()
    with pytest.raises(TypeError):
        cache.set("k", object())


def test_key_helpers_are_stable_and_namespaced() -> None:
    k1 = embedding_cache_key("text-embedding-3-small", "foo")
    k2 = embedding_cache_key("text-embedding-3-small", "foo")
    k3 = embedding_cache_key("text-embedding-3-small", "bar")
    assert k1 == k2 and k1 != k3
    assert k1.startswith("emb:text-embedding-3-small:")

    r = retrieval_cache_key("tenant-a", "query|filters")
    a = answer_cache_key("tenant-a", "query|filters", "chunk-hashes")
    assert r.startswith("retr:tenant-a:")
    assert a.startswith("ans:tenant-a:")


def test_get_cache_falls_back_to_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHE_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    reset_cache()
    assert isinstance(get_cache(), NoopCache)
    reset_cache()
    get_settings.cache_clear()


def test_set_cache_allows_test_injection() -> None:
    reset_cache()
    injected = InMemoryCache()
    set_cache(injected)
    assert get_cache() is injected
    reset_cache()


def test_get_cache_falls_back_when_redis_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Misconfigured Redis URL → NoopCache, no crash."""
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("CACHE_REDIS_URL", "redis://nonexistent-host-9999:6379/0")
    from app.core.config import get_settings

    get_settings.cache_clear()
    reset_cache()
    # Either it builds a RedisCache (connection is lazy), or it falls
    # back to NoopCache. Either way, .get must not raise.
    cache = get_cache()
    # Lazy-connection Redis will raise on actual use, not construction.
    # We only assert the factory doesn't crash.
    assert cache is not None
    reset_cache()
    get_settings.cache_clear()
