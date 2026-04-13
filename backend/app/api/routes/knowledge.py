from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.security import AuthContext, require_roles
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


@router.post("/upload", response_model=KnowledgeUploadAccepted, status_code=status.HTTP_202_ACCEPTED)
async def upload_knowledge_document(
    _: AuthContext = Depends(require_roles("admin", "operator")),
    file: UploadFile = File(...),
    tenant_id: str = Form("default-tenant"),
    customer_id: str = Form("default-customer"),
) -> KnowledgeUploadAccepted:
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")

    try:
        document_id = create_ingestion_job(
            file_bytes=file_bytes,
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
        submit_ingestion(document_id)
        job = get_job(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return KnowledgeDeleteResult(
        document_id=result.document_id,
        filename=result.filename,
        chunk_count=result.chunk_count,
    )
