from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal, init_db
from app.services.ingestion.chunker import chunk_document
from app.services.ingestion.loader import get_object_storage
from app.services.ingestion.parser import parse_document
from app.services.rag.index_builder import build_vector_records
from app.services.rag.vector_store import get_vector_store


@dataclass(frozen=True)
class IngestionResult:
    job_id: str
    document_id: str
    status: str
    chunk_count: int


@dataclass(frozen=True)
class KnowledgeJobSnapshot:
    job_id: str
    document_id: str
    filename: str
    status: str
    chunk_count: int
    tenant_id: str
    customer_id: str
    created_at: object
    updated_at: object


def create_ingestion_job(
    *,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    tenant_id: str,
    customer_id: str,
) -> str:
    init_db()
    object_storage = get_object_storage()
    stored_object = object_storage.store(file_bytes=file_bytes, filename=filename, content_type=content_type)

    document_id = str(uuid4())
    job_id = str(uuid4())

    with SessionLocal() as session:
        session.add(
            KnowledgeDocument(
                id=document_id,
                job_id=job_id,
                tenant_id=tenant_id,
                customer_id=customer_id,
                filename=filename,
                content_type=content_type,
                storage_key=stored_object.storage_key,
                status="uploaded",
                chunk_count=0,
                attributes_json={"size_bytes": stored_object.size_bytes},
            )
        )
        session.commit()

    return document_id


def run_ingestion_job(document_id: str) -> IngestionResult:
    init_db()
    object_storage = get_object_storage()

    with SessionLocal() as session:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise ValueError(f"document {document_id} not found")

        document.status = "processing"
        session.commit()

        try:
            file_bytes = object_storage.read(document.storage_key)
            parsed_document = parse_document(file_bytes, document.filename, document.content_type)
            chunk_payloads = chunk_document(parsed_document)

            chunks: list[KnowledgeChunk] = []
            for payload in chunk_payloads:
                chunk = KnowledgeChunk(
                    id=str(uuid4()),
                    document_id=document.id,
                    tenant_id=document.tenant_id,
                    customer_id=document.customer_id,
                    chunk_index=payload.chunk_index,
                    title=payload.title,
                    content=payload.content,
                    attributes_json=payload.attributes,
                )
                session.add(chunk)
                chunks.append(chunk)

            session.flush()

            vector_records = build_vector_records(chunks)
            vector_ids = get_vector_store().upsert(vector_records)

            for chunk in chunks:
                chunk.vector_id = vector_ids.get(chunk.id)

            document.status = "completed"
            document.parser_name = parsed_document.parser_name
            document.chunk_count = len(chunks)
            document.error_message = None
            session.commit()
            session.refresh(document)
        except Exception as exc:
            document.status = "failed"
            document.error_message = str(exc)
            session.commit()
            raise

        return IngestionResult(
            job_id=document.job_id,
            document_id=document.id,
            status=document.status,
            chunk_count=document.chunk_count,
        )


def start_ingestion(
    *,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    tenant_id: str,
    customer_id: str,
) -> IngestionResult:
    document_id = create_ingestion_job(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        tenant_id=tenant_id,
        customer_id=customer_id,
    )
    return run_ingestion_job(document_id)


def get_job(document_id: str) -> KnowledgeJobSnapshot:
    with SessionLocal() as session:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise ValueError(f"document {document_id} not found")
        return KnowledgeJobSnapshot(
            job_id=document.job_id,
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            chunk_count=document.chunk_count,
            tenant_id=document.tenant_id,
            customer_id=document.customer_id,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


def list_jobs() -> list[KnowledgeJobSnapshot]:
    with SessionLocal() as session:
        documents = session.scalars(
            select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
        ).all()

    return [
        KnowledgeJobSnapshot(
            job_id=document.job_id,
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            chunk_count=document.chunk_count,
            tenant_id=document.tenant_id,
            customer_id=document.customer_id,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
        for document in documents
    ]
