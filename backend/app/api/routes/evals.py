from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.metrics import observe_eval_run
from app.core.security import AuthContext, require_roles
from app.db.models.eval import EvalRun
from app.db.session import get_session, init_db
from app.schemas.eval import EvalDetailPayload, EvalRunCreateRequest, EvalRunListResponse, EvalRunPayload
from app.services.eval.dataset_loader import ensure_builtin_eval_dataset
from app.services.eval.runner import run_eval


router = APIRouter(prefix="/api/evals", tags=["evals"])


def _to_payload(row: EvalRun) -> EvalRunPayload:
    return EvalRunPayload(
        id=row.id,
        dataset_name=row.dataset_name,
        status=row.status,
        question_count=row.question_count,
        metrics=row.metrics,
        details=[EvalDetailPayload.model_validate(item) for item in row.details],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/runs", response_model=EvalRunListResponse)
def list_eval_runs(
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> EvalRunListResponse:
    init_db()
    rows = session.execute(select(EvalRun).order_by(EvalRun.created_at.desc())).scalars().all()
    return EvalRunListResponse(items=[_to_payload(row) for row in rows])


@router.post("/runs", response_model=EvalRunPayload, status_code=status.HTTP_201_CREATED)
def create_eval_run(
    payload: EvalRunCreateRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> EvalRunPayload:
    init_db()
    try:
        dataset = ensure_builtin_eval_dataset(session, payload.dataset_name)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="eval dataset not found") from error

    eval_run = run_eval(dataset.id)
    observe_eval_run(eval_run.dataset_name, eval_run.status)
    return _to_payload(eval_run)
