from pathlib import Path

from app.core.config import get_settings
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from tests.conftest import DOCX_CONTENT_TYPE


def test_upload_endpoint_returns_job_id(client, docx_file: bytes) -> None:
    response = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 202

    payload = response.json()
    assert payload["job_id"]
    assert payload["document_id"]
    assert payload["status"] == "completed"

    jobs_response = client.get("/api/knowledge/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["items"][0]["chunk_count"] > 0


def test_reindex_endpoint_rebuilds_document_vectors(client, docx_file: bytes) -> None:
    upload_response = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert upload_response.status_code == 202

    document_id = upload_response.json()["document_id"]

    response = client.post(
        "/api/knowledge/reindex",
        json={"document_id": document_id},
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["document_count"] == 1
    assert payload["chunk_count"] > 0
    assert payload["scope"] == "document"
    assert payload["document_ids"] == [document_id]


def test_jobs_mark_documents_for_reindex_when_embedding_profile_changes(
    client,
    docx_file: bytes,
    monkeypatch,
) -> None:
    upload_response = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert upload_response.status_code == 202

    initial_jobs = client.get("/api/knowledge/jobs")
    assert initial_jobs.status_code == 200
    initial_job = initial_jobs.json()["items"][0]
    assert initial_job["requires_reindex"] is False
    assert initial_job["stored_embedding_profile"]["provider"] == "deterministic"
    assert initial_job["current_embedding_profile"]["provider"] == "deterministic"

    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "demo-key")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1536")

    from app.core.config import get_settings

    get_settings.cache_clear()

    changed_jobs = client.get("/api/knowledge/jobs")
    assert changed_jobs.status_code == 200
    changed_job = changed_jobs.json()["items"][0]
    assert changed_job["requires_reindex"] is True
    assert changed_job["stored_embedding_profile"]["provider"] == "deterministic"
    assert changed_job["current_embedding_profile"]["provider"] == "openai-compatible"


def test_reindex_endpoint_can_target_only_stale_documents(
    client,
    docx_file: bytes,
    monkeypatch,
) -> None:
    first_upload = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy-v1.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert first_upload.status_code == 202
    first_document_id = first_upload.json()["document_id"]

    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "demo-key")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "6")

    from app.core.config import get_settings

    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.services.rag.index_builder.texts_to_embeddings",
        lambda texts, dimension: [[1.0] + [0.0] * (dimension - 1) for _ in texts],
    )

    second_upload = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy-v2.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert second_upload.status_code == 202

    response = client.post("/api/knowledge/reindex", json={"stale_only": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "stale"
    assert payload["document_count"] == 1
    assert payload["document_ids"] == [first_document_id]


def test_embedding_readiness_endpoint_reports_missing_gateway_config(client, monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.delenv("EMBEDDING_API_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    from app.core.config import get_settings

    get_settings.cache_clear()

    response = client.get("/api/knowledge/embedding-readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai-compatible"
    assert payload["configured"] is False
    assert payload["available"] is False
    assert payload["status"] == "missing_config"


def test_embedding_smoke_test_endpoint_reports_vector_dimension(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.rag.embedding_client.text_to_embedding",
        lambda text, dimension: [0.1, 0.2, 0.3, 0.4],
    )

    response = client.post("/api/knowledge/embedding-smoke-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["available"] is True
    assert payload["vector_dimension"] == 4
    assert payload["latency_ms"] >= 0
    assert payload["sample_text"]


def test_embedding_smoke_test_endpoint_returns_missing_config_when_gateway_not_configured(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.delenv("EMBEDDING_API_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    from app.core.config import get_settings

    get_settings.cache_clear()

    response = client.post("/api/knowledge/embedding-smoke-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai-compatible"
    assert payload["configured"] is False
    assert payload["available"] is False
    assert payload["status"] == "missing_config"


def test_delete_endpoint_removes_document_chunks_and_source_file(client, docx_file: bytes) -> None:
    upload_response = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert upload_response.status_code == 202

    document_id = upload_response.json()["document_id"]
    settings = get_settings()

    with SessionLocal() as session:
        document = session.get(KnowledgeDocument, document_id)
        assert document is not None
        storage_path = Path(settings.object_storage_root) / document.storage_key
        assert storage_path.exists()

    response = client.delete(f"/api/knowledge/documents/{document_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["filename"] == "policy.docx"
    assert payload["chunk_count"] > 0

    jobs_response = client.get("/api/knowledge/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["items"] == []

    with SessionLocal() as session:
        assert session.get(KnowledgeDocument, document_id) is None
        remaining_chunks = session.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).count()
        assert remaining_chunks == 0

    assert storage_path.exists() is False
