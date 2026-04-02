from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from app.services.ingestion.pipeline import start_ingestion


def test_docx_ingestion_persists_document_and_chunks(docx_file: bytes) -> None:
    result = start_ingestion(
        file_bytes=docx_file,
        filename="policy.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        tenant_id="t1",
        customer_id="c1",
    )

    assert result.status == "completed"
    assert result.chunk_count > 0

    with SessionLocal() as session:
        document = session.get(KnowledgeDocument, result.document_id)
        chunks = (
            session.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == result.document_id)
            .order_by(KnowledgeChunk.chunk_index.asc())
            .all()
        )

    assert document is not None
    assert document.filename == "policy.docx"
    assert document.status == "completed"
    assert len(chunks) == result.chunk_count
    assert "Travel Policy" in chunks[0].content
