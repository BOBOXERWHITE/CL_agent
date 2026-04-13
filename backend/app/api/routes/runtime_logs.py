from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthContext, require_roles
from app.db.session import get_session, init_db
from app.schemas.runtime_log import RuntimeLogListResponse, RuntimeLogPayload
from app.services.runtime_logs import get_runtime_log, list_runtime_logs


router = APIRouter(prefix="/api/logs", tags=["runtime-logs"])


@router.get("/runtime", response_model=RuntimeLogListResponse)
def get_runtime_logs(
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
    path: str | None = None,
    status_code: int | None = None,
    request_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> RuntimeLogListResponse:
    init_db()
    rows = list_runtime_logs(
        session,
        path=path,
        status_code=status_code,
        request_id=request_id,
        tenant_id=tenant_id,
        session_id=session_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return RuntimeLogListResponse(items=[RuntimeLogPayload.model_validate(row) for row in rows])


@router.get("/runtime/{runtime_log_id}", response_model=RuntimeLogPayload)
def get_runtime_log_detail(
    runtime_log_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> RuntimeLogPayload:
    init_db()
    row = get_runtime_log(session, runtime_log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="runtime log not found")
    return RuntimeLogPayload.model_validate(row)
