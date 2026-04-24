"""Audit recording helper.

Usage from a route handler::

    record_audit(
        session,
        request=request,
        ctx=context,
        action="chat.ask",
        target_type="ChatSession",
        target_id=session_id,
        payload={"question_chars": len(payload.question)},
    )
    session.commit()

The helper writes the row in the **same transaction** as the surrounding
business work. If the business commit fails, the audit insert rolls back
with it -- the alternative (separate transaction) would log actions that
never happened, which is worse than dropping logs.

Sanitisation: ``payload`` is shallow-copied and any key whose lowercase
form contains one of the known-secret substrings (``password``, ``token``,
``secret``, ``apikey``, ``api_key``, ``authorization``) is rewritten to
``"***"``. Routes should still avoid putting sensitive values in payload
to begin with -- this is defence in depth, not a free pass.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.deps import RequestContext
from app.db.models.audit_log import AuditLog

_REDACT_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "token",
    "secret",
    "apikey",
    "api_key",
    "authorization",
)
_REDACTED = "***"


def _sanitize(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Strip known-sensitive keys + run PII redaction on string values.

    Two passes:

    1. **Key-based blacklist** (``_REDACT_SUBSTRINGS``): replaces values
       whose key name smells like a credential (``password``, ``token``,
       ``secret``, etc.) with ``***``.
    2. **Value-based PII redaction** (P7.2): every remaining string
       value is passed through the guardrails regex layer so e.g.
       a user question containing a phone number gets ``[PHONE]``.

    Non-string values are untouched.
    """
    if not payload:
        return {}
    from app.core.guardrails.redaction import redact_text

    safe: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(needle in lowered for needle in _REDACT_SUBSTRINGS):
            safe[key] = _REDACTED
        elif isinstance(value, str):
            safe[key] = redact_text(value)
        else:
            safe[key] = value
    return safe


def _client_ip(request: Request) -> str | None:
    # Prefer ``X-Forwarded-For`` first hop when behind a proxy. We only
    # store the first IP; downstream observability should also strip and
    # validate against the trusted proxy chain.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return None


def record_audit(
    session: Session,
    *,
    request: Request,
    ctx: RequestContext,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one audit_log row in the current session.

    The caller decides when to ``commit`` -- typically after the business
    insert/update so audit and business work are atomic.
    """
    row = AuditLog(
        id=str(uuid4()),
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        request_id=ctx.request_id,
        payload_json=_sanitize(payload),
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    session.add(row)
    return row


__all__ = ["record_audit"]
