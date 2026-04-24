"""Developer-only JWT minting endpoint.

Purpose: during development and CI, tests need a way to obtain a valid JWT
for the ``Authorization: Bearer ...`` header without standing up a real
identity provider. This route hands one back, but only when
``settings.jwt_dev_token_endpoint_enabled`` is True. Production deployments
must flip that flag off so an attacker cannot self-sign arbitrary tenant
credentials.

Safety rails:
- Refuses to run if ``APP_ENV == "production"``.
- Enforced ``dev`` / ``development`` / ``test`` / ``integration`` env names
  are the only ones where signing is permitted.
- No authentication required to call this endpoint -- that is the point --
  so it MUST NOT be reachable from production traffic.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.errors import Forbidden
from app.core.jwt import encode_token
from app.core.rate_limit import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


_ALLOWED_ENVS = {"dev", "development", "test", "integration"}


class DevTokenRequest(BaseModel):
    user_id: str = Field(default="dev-user", min_length=1, max_length=64)
    tenant_id: str = Field(default="default-tenant", min_length=1, max_length=64)
    roles: tuple[str, ...] = Field(default=("admin",), min_length=1)
    expires_in_minutes: int | None = Field(default=None, ge=1, le=24 * 60)


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


@router.post("/dev-token", response_model=DevTokenResponse)
@limiter.limit(lambda: get_settings().rate_limit_auth_dev_token)
def issue_dev_token(
    request: Request, response: Response, payload: DevTokenRequest
) -> DevTokenResponse:
    settings = get_settings()

    if not settings.jwt_dev_token_endpoint_enabled:
        raise Forbidden("dev-token endpoint is disabled", error_code="DEV_TOKEN_DISABLED")
    if settings.app_env.lower() not in _ALLOWED_ENVS:
        raise Forbidden(
            "dev-token endpoint refuses to sign in this environment",
            error_code="DEV_TOKEN_ENV_FORBIDDEN",
            details={"app_env": settings.app_env},
        )

    token = encode_token(
        settings=settings,
        user_id=payload.user_id,
        tenant_id=payload.tenant_id,
        roles=payload.roles,
        expires_in_minutes=payload.expires_in_minutes,
    )
    return DevTokenResponse(
        access_token=token,
        expires_in_minutes=payload.expires_in_minutes or settings.jwt_expire_minutes,
    )


__all__ = ["router"]
