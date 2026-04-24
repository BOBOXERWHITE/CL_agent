"""Shared ``httpx.AsyncClient`` factory for RAG providers (P4.1).

FastAPI worker threads can only drive real parallel IO if the underlying
HTTP calls are ``await``-ed. The sync ``httpx.Client`` we ship in Phase 0
blocks the event loop, which means every ``POST /api/chat/ask`` serialises
all of its LLM / embedding / rerank round-trips regardless of uvicorn
workers.

This module owns the one ``AsyncClient`` per process. Creating a client
per request defeats connection pooling (and httpx logs a warning on
shutdown when dangling clients linger); creating it at import time
breaks the test environment, where ``get_settings`` still needs to
resolve. So we do lazy init + explicit close from the FastAPI lifespan.

Contract
--------

- ``get_async_http_client(timeout=...)`` returns the module-level client,
  creating it if needed.
- ``close_async_http_client()`` closes + forgets the instance; the next
  ``get_async_http_client`` call will build a fresh one.
- The lifespan calls ``close_async_http_client`` on shutdown. Tests can
  call it between cases to reset state.

We deliberately do NOT subclass ``AsyncClient`` — the sync providers
accept any httpx-like callable, and we want the async providers to stay
that way too. ``AsyncClient`` already handles retries via ``transport``,
but we leave retry logic in the client code (identical to the sync
path, same backoff ladder) so the two worlds behave the same way.
"""

from __future__ import annotations

import logging
from threading import Lock

import httpx

_log = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
_DEFAULT_MAX_CONNECTIONS = 100


_client: httpx.AsyncClient | None = None
_client_lock = Lock()


def get_async_http_client(
    *,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.AsyncClient:
    """Return the shared process-wide ``AsyncClient``.

    ``timeout`` only applies on first creation; subsequent calls return
    the existing client regardless of the passed value (a design we'd
    revisit if we ever needed per-provider timeouts, but today every
    provider's ~30s default is fine).
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        # Double-checked: another thread may have created it between the
        # check above and acquiring the lock.
        if _client is not None:
            return _client
        effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS
        limits = httpx.Limits(
            max_keepalive_connections=_DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
            max_connections=_DEFAULT_MAX_CONNECTIONS,
        )
        _client = httpx.AsyncClient(timeout=effective_timeout, limits=limits)
        _log.info(
            "async_http_client_created",
            extra={
                "timeout": str(effective_timeout),
                "max_connections": _DEFAULT_MAX_CONNECTIONS,
            },
        )
    return _client


async def close_async_http_client() -> None:
    """Close + forget the shared client. Safe to call when no client
    exists (idempotent shutdown path for the lifespan and tests).
    """
    global _client
    client = _client
    _client = None
    if client is not None:
        try:
            await client.aclose()
        except Exception as exc:  # we never want shutdown to raise
            _log.warning(
                "async_http_client_close_failed",
                extra={"error": repr(exc)},
            )


__all__ = [
    "close_async_http_client",
    "get_async_http_client",
]
