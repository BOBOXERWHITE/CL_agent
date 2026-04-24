from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.api.guards import require_tenant_match
from app.core.errors import NotFound
from app.core.metrics import observe_eval_run
from app.core.security import AuthContext, require_roles
from app.db.models.eval import EvalRun
from app.db.session import get_session
from app.schemas.eval import (
    EvalDetailPayload,
    EvalRunCreateRequest,
    EvalRunListResponse,
    EvalRunPayload,
)
from app.services.eval.dataset_loader import ensure_builtin_eval_dataset
from app.services.eval.retrieval_runner import (
    RetrievalSample,
    run_retrieval_eval,
)
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
    rows = session.execute(select(EvalRun).order_by(EvalRun.created_at.desc())).scalars().all()
    return EvalRunListResponse(items=[_to_payload(row) for row in rows])


@router.post("/runs", response_model=EvalRunPayload, status_code=status.HTTP_201_CREATED)
def create_eval_run(
    payload: EvalRunCreateRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> EvalRunPayload:
    try:
        dataset = ensure_builtin_eval_dataset(session, payload.dataset_name)
    except LookupError as error:
        raise NotFound("eval dataset not found", error_code="EVAL_DATASET_NOT_FOUND") from error

    eval_run = run_eval(dataset.id)
    observe_eval_run(eval_run.dataset_name, eval_run.status)
    return _to_payload(eval_run)


# --- Retrieval evaluation (P2.5 接入) ----------------------------------


class RetrievalSamplePayload(BaseModel):
    """One sample for a retrieval benchmark run."""

    query: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    relevant_chunk_ids: list[str] = Field(default_factory=list)


class RetrievalEvalRequest(BaseModel):
    samples: list[RetrievalSamplePayload] = Field(default_factory=list)
    retrieve_top_k: int = Field(default=10, ge=1, le=50)


class PerSamplePayload(BaseModel):
    query: str
    retrieved_chunk_ids: list[str]
    relevant_chunk_ids: list[str]
    recall_at_5: float
    recall_at_10: float
    precision_at_5: float
    ndcg_at_10: float
    reciprocal_rank: float
    latency_ms: float


class RetrievalEvalResponse(BaseModel):
    sample_count: int
    metrics: dict[str, float]
    per_sample: list[PerSamplePayload]


@router.post(
    "/retrieval-runs",
    response_model=RetrievalEvalResponse,
    status_code=status.HTTP_200_OK,
)
def run_retrieval_benchmark(
    payload: RetrievalEvalRequest,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> RetrievalEvalResponse:
    """Drive a retrieval benchmark and return recall@k / MRR / nDCG.

    Every sample's ``tenant_id`` must match the caller's JWT claim --
    cross-tenant evaluation is an admin escalation path that belongs in
    a dedicated endpoint, not here.
    """
    samples: list[RetrievalSample] = []
    for item in payload.samples:
        tenant_id = require_tenant_match(item.tenant_id, context)
        samples.append(
            RetrievalSample(
                query=item.query,
                tenant_id=tenant_id,
                customer_id=item.customer_id,
                relevant_chunk_ids=tuple(item.relevant_chunk_ids),
            )
        )

    report = run_retrieval_eval(samples, retrieve_top_k=payload.retrieve_top_k)
    return RetrievalEvalResponse(
        sample_count=report.sample_count,
        metrics=report.metrics,
        per_sample=[
            PerSamplePayload(
                query=r.query,
                retrieved_chunk_ids=list(r.retrieved_chunk_ids),
                relevant_chunk_ids=list(r.relevant_chunk_ids),
                recall_at_5=r.recall_at_5,
                recall_at_10=r.recall_at_10,
                precision_at_5=r.precision_at_5,
                ndcg_at_10=r.ndcg_at_10,
                reciprocal_rank=r.reciprocal_rank,
                latency_ms=r.latency_ms,
            )
            for r in report.per_sample
        ],
    )
