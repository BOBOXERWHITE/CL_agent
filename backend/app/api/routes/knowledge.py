from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.api.guards import require_tenant_match
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.errors import BadRequest, NotFound, UpstreamError
from app.core.rate_limit import limiter
from app.core.security import AuthContext, require_roles
from app.db.session import get_session
from app.schemas.knowledge import (
    KnowledgeDeleteResult,
    KnowledgeEmbeddingReadiness,
    KnowledgeEmbeddingSmokeTest,
    KnowledgeJob,
    KnowledgeJobList,
    KnowledgeRebuildRequest,
    KnowledgeRebuildResult,
    KnowledgeUploadAccepted,
)
from app.services.ingestion.pipeline import (
    create_ingestion_job,
    delete_knowledge_document,
    get_job,
    list_jobs,
    rebuild_knowledge_index,
)
from app.services.rag.embedding_client import check_embedding_readiness, run_embedding_smoke_test
from app.workers.tasks import submit_ingestion

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post(
    "/upload", response_model=KnowledgeUploadAccepted, status_code=status.HTTP_202_ACCEPTED
)
@limiter.limit(lambda: get_settings().rate_limit_knowledge_upload)
async def upload_knowledge_document(
    request: Request,
    response: Response,  # required by slowapi for X-RateLimit-* header injection
    _: AuthContext = Depends(require_roles("admin", "operator")),
    context: RequestContext = Depends(get_request_context),
    session: Session = Depends(get_session),
    file: UploadFile = File(...),
    tenant_id: str = Form("default-tenant"),
    customer_id: str = Form("default-customer"),
) -> KnowledgeUploadAccepted:
    file_bytes = await file.read()
    if not file_bytes:
        raise BadRequest("empty file", error_code="EMPTY_FILE")
    # P1.3: enforce form-supplied tenant_id matches the JWT claim.
    tenant_id = require_tenant_match(tenant_id, context)

    try:
        document_id = create_ingestion_job(
            file_bytes=file_bytes,
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
        submit_ingestion(
            document_id,
            tenant_id=tenant_id,
            user_id=context.user_id,
            trace_id=context.request_id,
        )
        job = get_job(document_id)
    except ValueError as exc:
        raise BadRequest(str(exc), error_code="INVALID_UPLOAD") from exc

    record_audit(
        session,
        request=request,
        ctx=context,
        action="knowledge.upload",
        target_type="KnowledgeDocument",
        target_id=document_id,
        payload={
            "filename": file.filename,
            "content_type": file.content_type,
            "byte_size": len(file_bytes),
            "status": job.status,
        },
    )
    session.commit()

    return KnowledgeUploadAccepted(
        job_id=job.job_id,
        document_id=job.document_id,
        status=job.status,
    )


@router.get("/jobs", response_model=KnowledgeJobList)
def list_knowledge_jobs(
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> KnowledgeJobList:
    items = [KnowledgeJob.model_validate(item) for item in list_jobs()]
    return KnowledgeJobList(items=items)


@router.get("/embedding-readiness", response_model=KnowledgeEmbeddingReadiness)
def get_embedding_readiness(
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> KnowledgeEmbeddingReadiness:
    readiness = check_embedding_readiness()
    return KnowledgeEmbeddingReadiness(
        provider=readiness.provider,
        model_name=readiness.model_name,
        configured=readiness.configured,
        available=readiness.available,
        status=readiness.status,
        message=readiness.message,
        endpoint=readiness.endpoint,
    )


@router.post("/embedding-smoke-test", response_model=KnowledgeEmbeddingSmokeTest)
def post_embedding_smoke_test(
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> KnowledgeEmbeddingSmokeTest:
    result = run_embedding_smoke_test()
    return KnowledgeEmbeddingSmokeTest(
        provider=result.provider,
        model_name=result.model_name,
        configured=result.configured,
        available=result.available,
        status=result.status,
        message=result.message,
        endpoint=result.endpoint,
        sample_text=result.sample_text,
        latency_ms=result.latency_ms,
        vector_dimension=result.vector_dimension,
    )


@router.post("/reindex", response_model=KnowledgeRebuildResult)
def rebuild_knowledge_vectors(
    payload: KnowledgeRebuildRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> KnowledgeRebuildResult:
    try:
        result = rebuild_knowledge_index(payload.document_id, stale_only=payload.stale_only)
    except ValueError as exc:
        if payload.document_id:
            raise NotFound(str(exc), error_code="DOCUMENT_NOT_FOUND") from exc
        raise BadRequest(str(exc), error_code="INVALID_REBUILD_REQUEST") from exc
    except RuntimeError as exc:
        raise UpstreamError(str(exc), error_code="REINDEX_UPSTREAM_FAILED") from exc

    return KnowledgeRebuildResult(
        scope=result.scope,
        document_count=result.document_count,
        chunk_count=result.chunk_count,
        document_ids=result.document_ids,
    )


@router.delete("/documents/{document_id}", response_model=KnowledgeDeleteResult)
def delete_knowledge_document_route(
    document_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> KnowledgeDeleteResult:
    try:
        result = delete_knowledge_document(document_id)
    except ValueError as exc:
        raise NotFound(str(exc), error_code="DOCUMENT_NOT_FOUND") from exc

    return KnowledgeDeleteResult(
        document_id=result.document_id,
        filename=result.filename,
        chunk_count=result.chunk_count,
    )
