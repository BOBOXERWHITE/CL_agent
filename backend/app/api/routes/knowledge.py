from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.schemas.knowledge import KnowledgeJob, KnowledgeJobList, KnowledgeUploadAccepted
from app.services.ingestion.pipeline import create_ingestion_job, get_job, list_jobs
from app.workers.tasks import submit_ingestion


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("/upload", response_model=KnowledgeUploadAccepted, status_code=status.HTTP_202_ACCEPTED)
async def upload_knowledge_document(
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
def list_knowledge_jobs() -> KnowledgeJobList:
    items = [KnowledgeJob.model_validate(item) for item in list_jobs()]
    return KnowledgeJobList(items=items)
