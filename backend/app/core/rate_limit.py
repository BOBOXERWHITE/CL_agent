"""Rate limiting — slowapi wrapper with tenant+user key and safe fallback.

Key derivation (per-request):
    1. If ``request.state.tenant_id`` + ``request.state.user_id`` are set
       (auth chain ran), use ``"{tenant}:{user}"`` so limits count per
       authenticated caller, not per IP. Two users behind the same proxy
       each get their own bucket.
    2. Otherwise fall back to the remote address. This covers /health,
       /api/auth/dev-token (no auth required), and any early-pipeline
       failures.

Storage: in-memory by default. Multi-worker deployments must switch to a
shared store (e.g. Redis) by passing ``storage_uri="redis://..."`` to the
``Limiter`` constructor. The P1.6 PoC stays in-memory and documents the
upgrade path.

Disabling: when ``settings.rate_limit_enabled=False`` the limiter object
is still instantiated (routes can still reference it), but we skip
attaching the exception handler and the ``@limiter.limit`` decorators
become no-ops via slowapi's own ``enabled=False`` plumbing.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings


def rate_limit_key(request: Request) -> str:
    """Prefer ``tenant:user`` identity from ``request.state``; else IP."""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    if tenant_id and user_id:
        return f"{tenant_id}:{user_id}"
    return get_remote_address(request)


def build_limiter() -> Limiter:
    """Construct the module-level Limiter the routes will decorate with."""
    settings = get_settings()
    return Limiter(
        key_func=rate_limit_key,
        default_limits=[settings.rate_limit_default],
        enabled=settings.rate_limit_enabled,
        # in-memory is fine for single-worker dev; prod overrides via
        # slowapi.extension.Limiter(..., storage_uri="redis://...").
        storage_uri="memory://",
        headers_enabled=True,  # adds X-RateLimit-* to successful responses
    )


# Module-level singleton. Import this in route modules:
#     from app.core.rate_limit import limiter
#     @limiter.limit(get_settings().rate_limit_chat_ask)
#
# When tests monkeypatch RATE_LIMIT_ENABLED, rebuild via reset_limiter().
limiter: Limiter = build_limiter()


def reset_limiter() -> None:
    """Rebuild the singleton after settings change (used by tests).

    Note: the route modules capture the limiter object in their
    ``@limiter.limit`` decorators at import time, so rebuilding the
    singleton after that point doesn't re-decorate. For test isolation use
    :func:`reset_limiter_storage` instead; it clears the counter on the
    existing singleton.
    """
    global limiter
    limiter = build_limiter()


def reset_limiter_storage() -> None:
    """Clear the in-memory counter without rebuilding the limiter.

    Safe to call from test fixtures -- decorators keep pointing at the same
    Limiter object, but every per-key counter starts fresh.
    """
    storage = getattr(limiter, "_storage", None)
    if storage is not None and hasattr(storage, "reset"):
        storage.reset()


__all__ = [
    "build_limiter",
    "limiter",
    "rate_limit_key",
    "reset_limiter",
    "reset_limiter_storage",
]
