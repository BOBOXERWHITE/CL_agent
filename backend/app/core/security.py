from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings


@dataclass(frozen=True)
class AuthContext:
    role: str
    token: str


def _token_role_map() -> dict[str, str]:
    settings = get_settings()
    mapping: dict[str, str] = {}
    for token in settings.auth_admin_tokens:
        mapping[token] = "admin"
    for token in settings.auth_operator_tokens:
        mapping[token] = "operator"
    for token in settings.auth_reviewer_tokens:
        mapping[token] = "reviewer"
    return mapping


def get_auth_context(request: Request) -> AuthContext:
    settings = get_settings()
    if not settings.auth_enabled:
        request.state.user_role = "admin"
        return AuthContext(role="admin", token="development-bypass")

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    role = _token_role_map().get(token)
    if role is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    request.state.user_role = role
    return AuthContext(role=role, token=token)


def require_roles(*allowed_roles: str) -> Callable[[AuthContext], AuthContext]:
    def dependency(auth_context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if auth_context.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return auth_context

    return dependency
