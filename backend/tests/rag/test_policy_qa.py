from app.services.rag import query_engine as query_engine_module
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from sqlalchemy import text

from app.db.session import SessionLocal


def test_policy_answer_includes_citations_and_confidence(client, seeded_policy_chunks: None) -> None:
    response = client.post(
        "/api/chat/ask",
        json={
            "question": "Can I book business class?",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["session_id"]
    assert payload["answer"]
    assert payload["citations"]
    assert payload["confidence"] >= 0
    assert payload["citations"][0]["document_id"]
    assert payload["citations"][0]["chunk_id"]
    assert payload["citations"][0]["snippet"]


def test_chat_session_persists_messages(client, seeded_policy_chunks: None) -> None:
    response = client.post(
        "/api/chat/ask",
        json={
            "question": "What is the hotel reimbursement cap in Beijing?",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )

    assert response.status_code == 200
    session_id = response.json()["session_id"]

    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT role, content FROM chat_message WHERE session_id = :session_id ORDER BY created_at ASC"),
            {"session_id": session_id},
        ).all()

    assert len(rows) == 2
    assert rows[0][0] == "user"
    assert rows[1][0] == "assistant"


def test_policy_answer_confidence_is_clamped_to_one(
    monkeypatch,
    seeded_policy_chunks: None,
) -> None:
    with SessionLocal() as session:
        row = session.execute(
            text(
                """
                SELECT knowledge_chunk.id AS chunk_id, knowledge_document.id AS document_id
                FROM knowledge_chunk
                JOIN knowledge_document ON knowledge_document.id = knowledge_chunk.document_id
                LIMIT 1
                """
            )
        ).one()

        chunk_model = session.get(KnowledgeChunk, row.chunk_id)
        document_model = session.get(KnowledgeDocument, row.document_id)

    assert chunk_model is not None
    assert document_model is not None

    monkeypatch.setattr(
        query_engine_module,
        "_vector_search",
        lambda question, tenant_id, customer_id, top_k: [(chunk_model, document_model, 1.65)],
    )
    monkeypatch.setattr(query_engine_module, "_lexical_search", lambda question, tenant_id, customer_id, top_k: [])

    result = query_engine_module.answer_policy_question(
        question="Can I book business class?",
        tenant_id="t1",
        customer_id="c1",
    )

    assert result.confidence == 1.0
