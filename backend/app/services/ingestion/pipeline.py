from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal, init_db
from app.services.ingestion.chunker import chunk_document
from app.services.ingestion.loader import get_object_storage
from app.services.ingestion.parser import parse_document
from app.services.rag.embedding_client import EmbeddingProfile, get_active_embedding_profile
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
    stored_embedding_profile: "KnowledgeEmbeddingProfileSnapshot | None"
    current_embedding_profile: "KnowledgeEmbeddingProfileSnapshot"
    requires_reindex: bool


@dataclass(frozen=True)
class KnowledgeEmbeddingProfileSnapshot:
    provider: str
    model_name: str
    dimension: int
    profile_key: str


@dataclass(frozen=True)
class KnowledgeRebuildSnapshot:
    scope: str
    document_count: int
    chunk_count: int
    document_ids: list[str]


@dataclass(frozen=True)
class KnowledgeDeleteSnapshot:
    document_id: str
    filename: str
    chunk_count: int


def _to_profile_snapshot(profile: EmbeddingProfile | dict[str, object] | None) -> KnowledgeEmbeddingProfileSnapshot | None:
    if profile is None:
        return None

    if isinstance(profile, EmbeddingProfile):
        return KnowledgeEmbeddingProfileSnapshot(
            provider=profile.provider,
            model_name=profile.model_name,
            dimension=profile.dimension,
            profile_key=profile.profile_key,
        )

    provider = str(profile.get("provider") or "").strip()
    model_name = str(profile.get("model_name") or "").strip()
    profile_key = str(profile.get("profile_key") or "").strip()
    dimension = int(profile.get("dimension") or 0)
    if not provider or not model_name or not profile_key or dimension <= 0:
        return None

    return KnowledgeEmbeddingProfileSnapshot(
        provider=provider,
        model_name=model_name,
        dimension=dimension,
        profile_key=profile_key,
    )


def _profile_to_json(profile: EmbeddingProfile) -> dict[str, object]:
    return {
        "provider": profile.provider,
        "model_name": profile.model_name,
        "dimension": profile.dimension,
        "profile_key": profile.profile_key,
    }


def _stored_profile_for_document(document: KnowledgeDocument) -> KnowledgeEmbeddingProfileSnapshot | None:
    attributes = document.attributes_json if isinstance(document.attributes_json, dict) else {}
    return _to_profile_snapshot(attributes.get("embedding_profile"))


def _requires_reindex(
    document: KnowledgeDocument,
    stored_profile: KnowledgeEmbeddingProfileSnapshot | None,
    current_profile: KnowledgeEmbeddingProfileSnapshot,
) -> bool:
    if document.status != "completed" or document.chunk_count <= 0:
        return False
    if stored_profile is None:
        return True
    return stored_profile.profile_key != current_profile.profile_key


def _build_job_snapshot(
    document: KnowledgeDocument,
    *,
    current_profile: KnowledgeEmbeddingProfileSnapshot,
) -> KnowledgeJobSnapshot:
    stored_profile = _stored_profile_for_document(document)
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
        stored_embedding_profile=stored_profile,
        current_embedding_profile=current_profile,
        requires_reindex=_requires_reindex(document, stored_profile, current_profile),
    )


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
    embedding_profile = get_active_embedding_profile()

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
                chunk.attributes_json = {
                    **(chunk.attributes_json or {}),
                    "embedding_profile": _profile_to_json(embedding_profile),
                }

            document.status = "completed"
            document.parser_name = parsed_document.parser_name
            document.chunk_count = len(chunks)
            document.error_message = None
            document.attributes_json = {
                **(document.attributes_json or {}),
                "embedding_profile": _profile_to_json(embedding_profile),
            }
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
        return _build_job_snapshot(
            document,
            current_profile=_to_profile_snapshot(get_active_embedding_profile()),
        )


def list_jobs() -> list[KnowledgeJobSnapshot]:
    with SessionLocal() as session:
        documents = session.scalars(
            select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
        ).all()
    current_profile = _to_profile_snapshot(get_active_embedding_profile())
    assert current_profile is not None

    return [_build_job_snapshot(document, current_profile=current_profile) for document in documents]


def rebuild_knowledge_index(
    document_id: str | None = None,
    *,
    stale_only: bool = False,
) -> KnowledgeRebuildSnapshot:
    init_db()
    embedding_profile = get_active_embedding_profile()
    current_profile = _to_profile_snapshot(embedding_profile)
    assert current_profile is not None

    with SessionLocal() as session:
        query = (
            select(KnowledgeDocument)
            .options(selectinload(KnowledgeDocument.chunks))
            .where(KnowledgeDocument.status == "completed")
            .order_by(KnowledgeDocument.created_at.desc())
        )
        if document_id:
            query = query.where(KnowledgeDocument.id == document_id)

        documents = session.scalars(query).unique().all()

        if not documents:
            if document_id:
                raise ValueError(f"document {document_id} not found")
            raise ValueError("no completed documents available for reindex")

        if stale_only and not document_id:
            documents = [
                document
                for document in documents
                if _requires_reindex(document, _stored_profile_for_document(document), current_profile)
            ]
            if not documents:
                raise ValueError("no stale documents available for reindex")

        chunks: list[KnowledgeChunk] = []
        for document in documents:
            chunks.extend(document.chunks)

        if not chunks:
            raise ValueError("no chunks available for reindex")

        vector_records = build_vector_records(chunks)
        vector_ids = get_vector_store().upsert(vector_records)

        for chunk in chunks:
            chunk.vector_id = vector_ids.get(chunk.id)
            chunk.attributes_json = {
                **(chunk.attributes_json or {}),
                "embedding_profile": _profile_to_json(embedding_profile),
            }

        for document in documents:
            document.attributes_json = {
                **(document.attributes_json or {}),
                "embedding_profile": _profile_to_json(embedding_profile),
            }

        session.commit()

        return KnowledgeRebuildSnapshot(
            scope="document" if document_id else ("stale" if stale_only else "all"),
            document_count=len(documents),
            chunk_count=len(chunks),
            document_ids=[document.id for document in documents],
        )


def delete_knowledge_document(document_id: str) -> KnowledgeDeleteSnapshot:
    init_db()
    object_storage = get_object_storage()
    vector_store = get_vector_store()

    with SessionLocal() as session:
        document = session.scalars(
            select(KnowledgeDocument)
            .options(selectinload(KnowledgeDocument.chunks))
            .where(KnowledgeDocument.id == document_id)
        ).unique().one_or_none()

        if document is None:
            raise ValueError(f"document {document_id} not found")

        chunk_ids = [chunk.id for chunk in document.chunks]
        snapshot = KnowledgeDeleteSnapshot(
            document_id=document.id,
            filename=document.filename,
            chunk_count=len(chunk_ids),
        )

        if chunk_ids:
            vector_store.delete(chunk_ids)

        object_storage.delete(document.storage_key)
        session.delete(document)
        session.commit()

        return snapshot
