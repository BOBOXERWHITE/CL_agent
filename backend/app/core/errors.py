"""Unified application exception hierarchy.

Why a hierarchy instead of raising ``HTTPException`` directly?

- Route handlers stay thin: they say "not found", not "return 404 with this
  specific error schema".
- Error codes are machine-stable and UI-translatable.
- Cross-cutting concerns (logging, metrics, request_id propagation) are
  handled by a single global exception handler.
- Upstream failures (LLM / Milvus / MinIO / DB) get wrapped into a typed
  ``UpstreamError`` instead of leaking a random 500 ``Exception``.

Mapping:

    AppException              base, 500
    ├─ BadRequest             400
    ├─ Unauthorized           401
    ├─ Forbidden              403
    ├─ NotFound               404
    ├─ Conflict               409
    ├─ Unprocessable          422
    ├─ RateLimited            429
    ├─ UpstreamError          502
    └─ ServiceUnavailable     503

Usage from a route handler::

    from app.core.errors import NotFound

    if template is None:
        raise NotFound("prompt template not found",
                       error_code="PROMPT_TEMPLATE_NOT_FOUND")
"""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """Base class for application-level exceptions.

    Subclasses override ``status_code`` and ``default_error_code``. Callers can
    further customize ``error_code`` and ``details`` per raise site.
    """

    status_code: int = 500
    default_error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "",
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.error_code: str = error_code or self.default_error_code
        self.details: dict[str, Any] = details or {}


class BadRequest(AppException):
    status_code = 400
    default_error_code = "BAD_REQUEST"


class Unauthorized(AppException):
    status_code = 401
    default_error_code = "UNAUTHORIZED"


class Forbidden(AppException):
    status_code = 403
    default_error_code = "FORBIDDEN"


class NotFound(AppException):
    status_code = 404
    default_error_code = "NOT_FOUND"


class Conflict(AppException):
    status_code = 409
    default_error_code = "CONFLICT"


class Unprocessable(AppException):
    """422 — body parsed fine but semantic validation failed."""

    status_code = 422
    default_error_code = "UNPROCESSABLE_ENTITY"


class RateLimited(AppException):
    status_code = 429
    default_error_code = "RATE_LIMITED"


class UpstreamError(AppException):
    """502 — an external dependency misbehaved.

    Use this to wrap failures from LLM / Milvus / MinIO / third-party HTTP
    calls so that the global handler reports them as 502 (not 500) and so the
    error_code survives for alerting / retry logic.
    """

    status_code = 502
    default_error_code = "UPSTREAM_ERROR"


class ServiceUnavailable(AppException):
    status_code = 503
    default_error_code = "SERVICE_UNAVAILABLE"


__all__ = [
    "AppException",
    "BadRequest",
    "Conflict",
    "Forbidden",
    "NotFound",
    "RateLimited",
    "ServiceUnavailable",
    "Unauthorized",
    "Unprocessable",
    "UpstreamError",
]
