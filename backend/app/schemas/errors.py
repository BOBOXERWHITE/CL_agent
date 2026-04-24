"""Error response schemas used by the global exception handlers.

Kept in ``schemas/`` so it shows up alongside other Pydantic models in OpenAPI
and client SDK generation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(..., description="Machine-stable error code, e.g. NOT_FOUND")
    message: str = Field(..., description="Human-readable explanation")
    request_id: str | None = Field(
        default=None,
        description="Correlates with server logs; forwarded as X-Request-ID",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured context (field errors, upstream info, etc.)",
    )


class ErrorResponse(BaseModel):
    error: ErrorBody


__all__ = ["ErrorBody", "ErrorResponse"]
