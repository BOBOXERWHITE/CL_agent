"""JWT token encoding, decoding, and claim schema.

The claim schema is intentionally small:

    sub          user id (string)
    tenant_id    hard-tenant key; used by routes and (in P1.4) PostgreSQL RLS
    roles        tuple of role strings ("admin" / "operator" / "reviewer")
    iat          issued at (unix seconds)
    exp          expiration (unix seconds)
    iss          issuer (matches settings.jwt_issuer)
    aud          audience (matches settings.jwt_audience)

``encode_token`` uses HS256 by default (see settings.jwt_algorithm). HS256 is
symmetric and suitable for a single backend. Migrating to RS256 (asymmetric,
for multi-service setups) is a one-line config change plus generating a
keypair -- no code changes needed.

On the decode side, failures fall into typed ``UnauthorizedReason`` values so
the caller can surface a specific error code in the response body (useful for
client apps that want to auto-refresh on ``TOKEN_EXPIRED`` vs. log out on
``INVALID_TOKEN``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import jwt as pyjwt

from app.core.config import Settings


class UnauthorizedReason(str, Enum):
    MISSING_TOKEN = "MISSING_TOKEN"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_NOT_YET_VALID = "TOKEN_NOT_YET_VALID"
    WRONG_AUDIENCE = "WRONG_AUDIENCE"
    WRONG_ISSUER = "WRONG_ISSUER"
    MISSING_CLAIM = "MISSING_CLAIM"


class TokenError(Exception):
    """Raised by decode_token when a JWT cannot be validated."""

    def __init__(self, reason: UnauthorizedReason, message: str) -> None:
        super().__init__(message)
        self.reason: UnauthorizedReason = reason
        self.message: str = message


@dataclass(frozen=True)
class TokenClaims:
    """Validated claim set returned from decode_token.

    Stored on ``request.state`` and hoisted into ``RequestContext`` in P1.2 so
    routes can read tenant_id / user_id / roles without trusting the request
    body.
    """

    sub: str
    tenant_id: str
    roles: tuple[str, ...]
    iat: int
    exp: int
    iss: str
    aud: str


def _now_ts() -> int:
    return int(datetime.now(UTC).timestamp())


def encode_token(
    *,
    settings: Settings,
    user_id: str,
    tenant_id: str,
    roles: tuple[str, ...],
    expires_in_minutes: int | None = None,
) -> str:
    """Sign a new JWT for the given subject + tenant + roles.

    Defaults to ``settings.jwt_expire_minutes`` if ``expires_in_minutes`` not
    provided. All tokens are signed with ``settings.jwt_algorithm`` (HS256 by
    default) using ``settings.jwt_secret_key``.
    """
    ttl_minutes = (
        expires_in_minutes if expires_in_minutes is not None else settings.jwt_expire_minutes
    )
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=ttl_minutes)

    payload: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": list(roles),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return pyjwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(*, settings: Settings, token: str) -> TokenClaims:
    """Verify signature + expected iss/aud + expiry, then return the claims.

    Raises :class:`TokenError` with a typed ``UnauthorizedReason`` on failure.
    """
    if not token:
        raise TokenError(UnauthorizedReason.MISSING_TOKEN, "missing bearer token")

    try:
        payload: dict[str, Any] = pyjwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise TokenError(UnauthorizedReason.TOKEN_EXPIRED, "token expired") from exc
    except pyjwt.ImmatureSignatureError as exc:
        raise TokenError(UnauthorizedReason.TOKEN_NOT_YET_VALID, "token not yet valid") from exc
    except pyjwt.InvalidAudienceError as exc:
        raise TokenError(UnauthorizedReason.WRONG_AUDIENCE, "wrong audience") from exc
    except pyjwt.InvalidIssuerError as exc:
        raise TokenError(UnauthorizedReason.WRONG_ISSUER, "wrong issuer") from exc
    except pyjwt.MissingRequiredClaimError as exc:
        raise TokenError(
            UnauthorizedReason.MISSING_CLAIM, f"missing required claim: {exc.claim}"
        ) from exc
    except pyjwt.InvalidTokenError as exc:
        raise TokenError(UnauthorizedReason.INVALID_TOKEN, "invalid token") from exc

    tenant_id = payload.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise TokenError(UnauthorizedReason.MISSING_CLAIM, "missing required claim: tenant_id")

    roles_raw = payload.get("roles", [])
    if not isinstance(roles_raw, list) or not all(isinstance(r, str) for r in roles_raw):
        raise TokenError(UnauthorizedReason.INVALID_TOKEN, "roles must be list of strings")

    return TokenClaims(
        sub=str(payload["sub"]),
        tenant_id=tenant_id,
        roles=tuple(roles_raw),
        iat=int(payload["iat"]),
        exp=int(payload["exp"]),
        iss=str(payload["iss"]),
        aud=str(payload["aud"]),
    )


__all__ = [
    "TokenClaims",
    "TokenError",
    "UnauthorizedReason",
    "_now_ts",
    "decode_token",
    "encode_token",
]
