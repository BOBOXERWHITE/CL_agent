"""Attach the slowapi Limiter to a FastAPI app.

Kept as a thin wrapper so ``main.py`` doesn't need to understand slowapi
internals; if we swap to another limiter (e.g. ``limits`` + custom middleware
once we go async), only this file changes.
"""

from __future__ import annotations

from fastapi import FastAPI
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import limiter


def attach_rate_limiter(app: FastAPI) -> None:
    """Register the module-level limiter on the FastAPI app.

    slowapi needs ``app.state.limiter`` set so its middleware / decorators
    can find the same limiter instance. The middleware itself enforces
    the ``default_limits`` on every route that does not opt in explicitly.
    """
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)


__all__ = ["attach_rate_limiter"]
