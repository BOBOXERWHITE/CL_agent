"""HTTP authentication: Bearer token -> AuthContext with role + tenant claim.

Two modes, selected by ``settings.jwt_enabled``:

1. **JWT mode** (``JWT_ENABLED=true``, production default once rolled out):
   Bearer token is a signed JWT. Tenant id, user id, and roles come from the
   verified claim set -- never from the request body.

2. **Static-token mode** (``JWT_ENABLED=false``, dev default until migration
   completes): Tokens are looked up in the three ``AUTH_*_TOKENS`` lists.
   Tenant id defaults to ``default-tenant`` because static tokens carry no
   claim. This mode is safe only in APP_ENV=development; ``main.py`` refuses
   to start a production app when JWT is disabled.

The ``auth_enabled=false`` shortcut -- previously returning ``admin`` with no
token at all -- has been **removed**. Even in static-token mode the client
must send a real token. Tests mint one via the ``/api/auth/dev-token`` route
or the pytest ``client`` fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import Forbidden, Unauthorized
from app.core.jwt import TokenClaims, TokenError, UnauthorizedReason, decode_token


@dataclass(frozen=True)
class AuthContext:
    """Authenticated caller context, surfaced to routes and request_state.

    ``tenant_id`` and ``user_id`` are filled from JWT claims when JWT mode is
    enabled; in static-token mode they fall back to well-known dev defaults
    so legacy tests keep working. Routes that need tenant isolation should
    use P1.3's ``require_tenant_match`` helper rather than reading tenant_id
    from the request body.
    """

    role: str
    token: str
    user_id: str = "dev-user"
    tenant_id: str = "default-tenant"
    roles: tuple[str, ...] = field(default_factory=tuple)
    claims: TokenClaims | None = None


def _static_token_role_map(settings: Settings) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for token in settings.auth_admin_tokens:
        mapping[token] = "admin"
    for token in settings.auth_operator_tokens:
        mapping[token] = "operator"
    for token in settings.auth_reviewer_tokens:
        mapping[token] = "reviewer"
    return mapping


def _primary_role(roles: tuple[str, ...]) -> str:
    """Resolve a single "primary" role for handlers that still check one role.

    Precedence: admin > operator > reviewer > (first role) > ''. A future
    refactor can remove this helper once every route migrates to
    ``require_roles(*allowed)`` checking the full set.
    """
    precedence = ("admin", "operator", "reviewer")
    for role in precedence:
        if role in roles:
            return role
    return roles[0] if roles else ""


def _extract_bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise Unauthorized(
            "missing bearer token", error_code=UnauthorizedReason.MISSING_TOKEN.value
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise Unauthorized(
            "missing bearer token", error_code=UnauthorizedReason.MISSING_TOKEN.value
        )
    return token


def _auth_via_jwt(token: str, settings: Settings) -> AuthContext:
    try:
        claims = decode_token(settings=settings, token=token)
    except TokenError as exc:
        raise Unauthorized(exc.message, error_code=exc.reason.value) from exc

    role = _primary_role(claims.roles)
    if not role:
        raise Unauthorized("token has no roles", error_code=UnauthorizedReason.MISSING_CLAIM.value)

    return AuthContext(
        role=role,
        token=token,
        user_id=claims.sub,
        tenant_id=claims.tenant_id,
        roles=claims.roles,
        claims=claims,
    )


def _auth_via_static_token(token: str, settings: Settings) -> AuthContext:
    role = _static_token_role_map(settings).get(token)
    if role is None:
        raise Unauthorized(
            "invalid bearer token", error_code=UnauthorizedReason.INVALID_TOKEN.value
        )
    return AuthContext(
        role=role,
        token=token,
        user_id=f"static-{role}",
        tenant_id="default-tenant",
        roles=(role,),
        claims=None,
    )


def get_auth_context(request: Request) -> AuthContext:
    settings = get_settings()
    token = _extract_bearer_token(request)

    if settings.jwt_enabled:
        context = _auth_via_jwt(token, settings)
    else:
        context = _auth_via_static_token(token, settings)

    request.state.user_role = context.role
    request.state.tenant_id = context.tenant_id
    request.state.user_id = context.user_id
    return context


def require_roles(*allowed_roles: str) -> Callable[[AuthContext], AuthContext]:
    """Dependency factory: 403 if the caller's role set is disjoint from ``allowed_roles``."""

    def dependency(auth_context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        caller_roles = set(auth_context.roles) if auth_context.roles else {auth_context.role}
        if caller_roles.isdisjoint(allowed_roles):
            raise Forbidden(
                "insufficient role",
                error_code="ROLE_FORBIDDEN",
                details={"required_any": list(allowed_roles), "caller": list(caller_roles)},
            )
        return auth_context

    return dependency


__all__ = ["AuthContext", "get_auth_context", "require_roles"]
