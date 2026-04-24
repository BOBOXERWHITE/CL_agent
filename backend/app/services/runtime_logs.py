from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime_log import RuntimeLog
from app.db.session import bypass_rls_session


def create_runtime_log(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
    tenant_id: str | None = None,
    customer_id: str | None = None,
    session_id: str | None = None,
    user_role: str | None = None,
    model_name: str | None = None,
    token_usage: dict[str, int] | None = None,
    error_message: str | None = None,
) -> None:
    # P7.2: redact PII from error_message before persisting. Error
    # traces often echo back user input (404 with the path they hit,
    # 422 with the bad value they sent). Running every string field
    # through the regex layer is cheap — empty / short strings exit
    # fast.
    from app.core.guardrails.redaction import redact_text

    safe_error = redact_text(error_message) if error_message else error_message
    with bypass_rls_session() as session:
        session.add(
            RuntimeLog(
                id=str(uuid4()),
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
                tenant_id=tenant_id,
                customer_id=customer_id,
                session_id=session_id,
                user_role=user_role,
                model_name=model_name,
                token_usage_json=token_usage or {},
                error_message=safe_error,
            )
        )
        session.commit()


def list_runtime_logs(
    session: Session,
    *,
    path: str | None = None,
    status_code: int | None = None,
    request_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
) -> list[RuntimeLog]:
    statement = select(RuntimeLog)
    if path:
        statement = statement.where(RuntimeLog.path == path)
    if status_code is not None:
        statement = statement.where(RuntimeLog.status_code == status_code)
    if request_id:
        statement = statement.where(RuntimeLog.request_id == request_id)
    if tenant_id:
        statement = statement.where(RuntimeLog.tenant_id == tenant_id)
    if session_id:
        statement = statement.where(RuntimeLog.session_id == session_id)
    if date_from is not None:
        statement = statement.where(RuntimeLog.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(RuntimeLog.created_at <= date_to)

    statement = statement.order_by(RuntimeLog.created_at.desc()).limit(max(1, min(limit, 200)))
    return list(session.execute(statement).scalars().all())


def get_runtime_log(session: Session, runtime_log_id: str) -> RuntimeLog | None:
    return session.get(RuntimeLog, runtime_log_id)


def utcnow() -> datetime:
    return datetime.now(UTC)
