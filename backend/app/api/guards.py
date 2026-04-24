"""Cross-cutting guards used by route handlers.

These are not FastAPI ``Depends`` dependencies; they are tiny imperative
helpers called inline at the top of a handler once the body has been
deserialised. Keeping them as plain functions makes the security-critical
check easy to grep for (search ``require_tenant_match``) and impossible
to forget by accident -- a missing call shows up immediately in the
P1.3 cross-tenant test suite.
"""

from __future__ import annotations

from app.api.deps import RequestContext
from app.core.errors import Forbidden

# Tokens that callers (typically tests or migrated dev code) can pass to
# explicitly opt in to the legacy "any tenant" behaviour. We keep this list
# tiny and only allow it for the dev defaults so a real prod deployment
# cannot accidentally bypass tenant isolation.
_LEGACY_TENANT_PLACEHOLDERS: frozenset[str] = frozenset({"default-tenant", "default-customer"})


def require_tenant_match(body_tenant_id: str | None, ctx: RequestContext) -> str:
    """Return the resolved tenant id, raising ``Forbidden`` on mismatch.

    Rules:
    - If the body omits ``tenant_id``, use the ctx tenant id. Implicit
      trust in the token is the safe default.
    - If the ctx tenant id is the **static-token placeholder**, accept any
      body value verbatim. Static tokens carry no real claim, so there is
      nothing to compare against. ``main.py`` refuses to start production
      without JWT enabled, so this branch only fires in dev/test.
    - In JWT mode (real claim), require an exact match or raise 403
      ``TENANT_MISMATCH``. This is the security-critical path.

    Returns the resolved tenant id so handlers can write a single line:
    ``tenant_id = require_tenant_match(payload.tenant_id, ctx)``.
    """
    if not body_tenant_id:
        return ctx.tenant_id
    # If the body just sent the schema default placeholder ("default-tenant"),
    # treat it as "client didn't supply a real value" and use the ctx value
    # instead. This avoids a false-positive mismatch when a JWT-mode client
    # forgets to set tenant_id but the Pydantic schema fills in a default.
    if (
        body_tenant_id in _LEGACY_TENANT_PLACEHOLDERS
        and ctx.tenant_id not in _LEGACY_TENANT_PLACEHOLDERS
    ):
        return ctx.tenant_id
    # Static-token mode: claim tenant_id is itself a placeholder; trust the
    # body for legacy compatibility. Production cannot reach this branch
    # because `_validate_production_security` forces JWT_ENABLED=true.
    if ctx.tenant_id in _LEGACY_TENANT_PLACEHOLDERS:
        return body_tenant_id
    if body_tenant_id == ctx.tenant_id:
        return body_tenant_id

    raise Forbidden(
        "tenant id in body does not match authenticated tenant",
        error_code="TENANT_MISMATCH",
        details={"body_tenant_id": body_tenant_id, "claim_tenant_id": ctx.tenant_id},
    )


__all__ = ["require_tenant_match"]
