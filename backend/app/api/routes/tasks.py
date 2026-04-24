"""Task observation + cancellation API (P4.5).

Reads from the ``task_run`` table populated by the P4.4 sink. Three
endpoints:

- ``GET /api/tasks``  — paginated list scoped to the caller's tenant,
  filterable by ``status``. The dashboard polls this.
- ``GET /api/tasks/{id}`` — single-row detail + result / error payloads.
- ``POST /api/tasks/{id}/cancel`` — reviewer-initiated revoke: issues
  ``celery_app.control.revoke(task_id, terminate=True)`` and flips the
  DB row to ``canceled``. Idempotent.

Cancel is scoped to ``admin / operator`` because a cancel mid-ingestion
can leave artefacts in object storage the user can't clean up; ordinary
reviewers can see the list but not cancel.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.api.guards import require_tenant_match
from app.core.audit import record_audit
from app.core.security import AuthContext, require_roles
from app.db.models.task_run import TaskRun
from app.db.session import get_session
from app.schemas.task_run import (
    TaskCancelRequest,
    TaskCancelResponse,
    TaskRunListResponse,
    TaskRunPayload,
)
from app.services.tasks import sink as task_sink

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _serialize(row: TaskRun) -> TaskRunPayload:
    return TaskRunPayload(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        task_name=row.task_name,
        status=row.status,
        idempotency_key=row.idempotency_key,
        input=row.input_json or {},
        result=row.result_json,
        error=row.error_json,
        retries=row.retries,
        trace_id=row.trace_id,
        summary=row.summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
    )


@router.get("", response_model=TaskRunListResponse)
def list_tasks(
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
    status_filter: str | None = Query(default=None, alias="status"),
    task_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskRunListResponse:
    """List task_run rows for the caller's tenant.

    Filter + paginate are mandatory query params with sane defaults
    (newest-first, 50-row page). ``status`` accepts one of the
    canonical sink statuses; unknown values yield an empty list rather
    than 400 — this keeps the dashboard robust when a new status is
    added server-side before the client ships.
    """
    request.state.request_id = context.request_id
    request.state.tenant_id = context.tenant_id

    query = select(TaskRun).where(TaskRun.tenant_id == context.tenant_id)
    count_query = (
        select(func.count()).select_from(TaskRun).where(TaskRun.tenant_id == context.tenant_id)
    )
    if status_filter:
        query = query.where(TaskRun.status == status_filter)
        count_query = count_query.where(TaskRun.status == status_filter)
    if task_name:
        query = query.where(TaskRun.task_name == task_name)
        count_query = count_query.where(TaskRun.task_name == task_name)

    query = query.order_by(TaskRun.created_at.desc()).limit(limit).offset(offset)
    rows = list(session.execute(query).scalars())
    total = int(session.execute(count_query).scalar_one())
    return TaskRunListResponse(
        items=[_serialize(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskRunPayload)
def get_task(
    task_id: str,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
    session: Session = Depends(get_session),
) -> TaskRunPayload:
    request.state.request_id = context.request_id
    request.state.tenant_id = context.tenant_id

    row = session.get(TaskRun, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    # Tenant scoping: an operator on tenant A must not read tenant B's
    # tasks even if they guess the id.
    require_tenant_match(row.tenant_id, context)
    return _serialize(row)


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
def cancel_task(
    task_id: str,
    payload: TaskCancelRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> TaskCancelResponse:
    """Cancel a running task. Idempotent.

    Contract:

    - Row not found → 404.
    - Row already in a terminal state other than ``canceled`` → 409
      (succeeded / failed runs can't be "canceled" retroactively).
    - Row already ``canceled`` → 200 with ``transitioned=false``.
    - Otherwise: ``revoke()`` the Celery task, ``mark_canceled`` in DB,
      write an audit row, return ``transitioned=true``.
    """
    request.state.request_id = context.request_id
    row = session.get(TaskRun, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    require_tenant_match(row.tenant_id, context)
    request.state.tenant_id = row.tenant_id

    if row.status in task_sink.TERMINAL_STATUSES and row.status != task_sink.STATUS_CANCELED:
        raise HTTPException(
            status_code=409,
            detail=f"task already in terminal status {row.status!r}, not cancelable",
        )

    if row.status == task_sink.STATUS_CANCELED:
        return TaskCancelResponse(task=_serialize(row), transitioned=False)

    # Tell Celery to stop running it (terminate=True kills a running
    # task). We do this before DB update so a successful revoke is
    # the operation's gate — if revoke throws (broker down), the row
    # stays in the current status and the reviewer can retry.
    try:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(task_id, terminate=True)
    except Exception as exc:  # broker errors, config issues, eager mode
        _log.warning(
            "celery_revoke_failed",
            extra={"task_id": task_id, "error": str(exc)},
        )
        # Do NOT raise: in eager mode there's nothing to revoke, and
        # we still want to mark the DB row canceled so the UI state
        # advances. The log line is the operator's signal.

    updated = task_sink.mark_canceled(session, task_id=task_id, note=payload.note)
    assert updated is not None  # we just fetched it above
    record_audit(
        session,
        request=request,
        ctx=context,
        action="task.cancel",
        target_type="TaskRun",
        target_id=task_id,
        payload={"note": payload.note, "previous_status": row.status},
    )
    session.commit()
    return TaskCancelResponse(task=_serialize(updated), transitioned=True)
