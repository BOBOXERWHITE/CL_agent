"""Global exception handlers registered on the FastAPI app.

Handlers (priority order):

1. ``AppException``     — domain exceptions (see ``app.core.errors``).
2. ``HTTPException``    — FastAPI / Starlette legacy raises; converted to the
   same JSON structure so clients see a consistent body.
3. ``RequestValidationError`` — Pydantic validation (422); field errors are
   surfaced in ``details.fields``.
4. ``Exception``        — catch-all 500 with a sanitized message. The real
   stack trace is logged via the request middleware that wraps call_next.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.core.errors import AppException
from app.schemas.errors import ErrorBody, ErrorResponse

_log = logging.getLogger("travel_ops.errors")


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _json(
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build the unified error response.

    Body format::

        {
          "detail": "<message>",        # legacy shim for existing clients
          "error": {
            "code": "<CODE>",
            "message": "<message>",
            "request_id": "...",
            "details": {...}
          }
        }

    ``detail`` is kept so existing clients/tests that read ``response["detail"]``
    keep working. ``error`` is the authoritative structured form.
    """
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=request_id,
            details=details or {},
        )
    )
    content = jsonable_encoder(body)
    content["detail"] = message
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(status_code=status_code, content=content, headers=headers)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    _log.warning(
        "app_exception",
        extra={
            "request_id": _request_id(request),
            "status_code": exc.status_code,
            "error_code": exc.error_code,
            "error_message": exc.message,
        },
    )
    return _json(
        status_code=exc.status_code,
        code=exc.error_code,
        message=exc.message or exc.default_error_code,
        request_id=_request_id(request),
        details=exc.details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Legacy code raising HTTPException(status_code=..., detail=...) still
    # works and reaches here; we reformat to the unified body.
    detail = exc.detail
    details: dict[str, Any] = {}
    if isinstance(detail, dict):
        # detail may already be structured by some older handler
        code = str(detail.get("code") or _code_for_status(exc.status_code))
        message = str(detail.get("message") or detail.get("detail") or "")
        details = {k: v for k, v in detail.items() if k not in {"code", "message"}}
    else:
        code = _code_for_status(exc.status_code)
        message = str(detail) if detail is not None else ""
    return _json(
        status_code=exc.status_code,
        code=code,
        message=message,
        request_id=_request_id(request),
        details=details,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _json(
        status_code=422,
        code="VALIDATION_ERROR",
        message="request body failed schema validation",
        request_id=_request_id(request),
        details={"fields": jsonable_encoder(exc.errors())},
    )


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """429 handler for slowapi ``RateLimitExceeded``.

    Reformat slowapi's default response into the unified envelope and
    preserve ``Retry-After`` so well-behaved clients back off correctly.
    """
    from slowapi.errors import RateLimitExceeded

    limit = getattr(exc, "limit", None) if isinstance(exc, RateLimitExceeded) else None
    details: dict[str, Any] = {}
    if limit is not None:
        details = {"limit": str(getattr(limit, "limit", "")), "remaining": 0}
    return _json(
        status_code=429,
        code="RATE_LIMITED",
        message="rate limit exceeded",
        request_id=_request_id(request),
        details=details,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _log.exception(
        "unhandled_exception",
        extra={
            "request_id": _request_id(request),
            "exception_type": type(exc).__name__,
        },
    )
    return _json(
        status_code=500,
        code="INTERNAL_ERROR",
        message="internal server error",
        request_id=_request_id(request),
    )


def _code_for_status(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        502: "UPSTREAM_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "ERROR")


def register_error_handlers(app: FastAPI) -> None:
    """Wire the four handlers above into the FastAPI app.

    Registered narrowest-to-widest so the most specific match wins.

    The ``type: ignore[arg-type]`` annotations reflect a known FastAPI typing
    quirk: its ``add_exception_handler`` signature demands a generic
    ``Exception`` argument even when the handler signature is correctly
    narrowed. See https://github.com/fastapi/fastapi/issues/5270.
    """
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]

    # slowapi rate limit (P1.6). Registered before the catch-all so 429s
    # don't fall through to the generic INTERNAL_ERROR handler.
    from slowapi.errors import RateLimitExceeded

    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.add_exception_handler(Exception, unhandled_exception_handler)
