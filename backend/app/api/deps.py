"""FastAPI request-scoped dependencies.

``RequestContext`` is the unified handle that route handlers use to read
authenticated identity (tenant_id / user_id / roles) and per-request
correlation data (request_id). It is populated from the verified JWT claim
set in JWT mode, or from the static-token AuthContext defaults in
static-token mode -- never from the request body.

P1.3 will add ``require_tenant_match(body_tenant_id, ctx)`` that compares a
client-supplied tenant_id against the one in the context and raises 403 on
mismatch, closing the cross-tenant escalation hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request

from app.core.security import AuthContext, get_auth_context


@dataclass(frozen=True)
class RequestContext:
    """Per-request handle exposed to route handlers.

    Always carries tenant_id / user_id / roles from the verified Bearer
    token. The previous version only carried ``request_id`` -- callers
    relying on body-supplied tenant ids should migrate via
    ``require_tenant_match`` (P1.3).
    """

    request_id: str
    tenant_id: str
    user_id: str
    role: str
    roles: tuple[str, ...]


def get_request_context(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> RequestContext:
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("x-request-id")
        or str(uuid4())
    )
    request.state.request_id = request_id
    request.state.tenant_id = auth.tenant_id
    request.state.user_id = auth.user_id
    request.state.user_role = auth.role
    return RequestContext(
        request_id=request_id,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        role=auth.role,
        roles=auth.roles or (auth.role,),
    )
