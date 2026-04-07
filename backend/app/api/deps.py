from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request


@dataclass(frozen=True)
class RequestContext:
    request_id: str


def get_request_context(request: Request) -> RequestContext:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = request_id
    return RequestContext(request_id=request_id)
