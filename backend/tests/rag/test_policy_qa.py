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


def test_answer_policy_question_rewrites_query_only_once(
    monkeypatch,
    seeded_policy_chunks: None,
) -> None:
    rewrite_calls = {"query_engine": 0, "retrievers": 0}

    def fake_rewrite_query(question: str):
        rewrite_calls["query_engine"] += 1
        return type(
            "RewriteResult",
            (),
            {
                "expanded_query": f"{question} 扩展词",
                "applied_rules": ["alias"],
            },
        )()

    monkeypatch.setattr(query_engine_module, "rewrite_query", fake_rewrite_query)
    monkeypatch.setattr(
        "app.services.rag.retrievers.rewrite_query",
        lambda question: (
            rewrite_calls.__setitem__("retrievers", rewrite_calls["retrievers"] + 1)
            or fake_rewrite_query(question)
        ),
    )

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
        "retrieve_hybrid",
        lambda query_text, tenant_id, customer_id, top_k: [
            query_engine_module.RetrievalHit(
                chunk=chunk_model,
                document=document_model,
                dense_score=0.81,
                lexical_score=0.62,
                combined_score=0.75,
            )
        ],
    )
    monkeypatch.setattr(query_engine_module, "retrieve_dense", lambda *args, **kwargs: [])
    monkeypatch.setattr(query_engine_module, "retrieve_lexical", lambda *args, **kwargs: [])

    result = query_engine_module.answer_policy_question(
        question="北京酒店报销上限是多少？",
        tenant_id="t1",
        customer_id="c1",
    )

    assert result.citations
    assert rewrite_calls["query_engine"] == 1
    assert rewrite_calls["retrievers"] == 0


def test_llm_gateway_readiness_endpoint_returns_status(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.chat.check_llm_readiness",
        lambda: type(
            "Readiness",
            (),
            {
                "provider": "openai-compatible",
                "model_name": "gpt-4o-mini",
                "configured": True,
                "available": True,
                "status": "ready",
                "message": "LLM 网关连通正常。",
                "endpoint": "https://gateway.example.com/v1",
            },
        )(),
    )

    response = client.get("/api/chat/llm-readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["status"] == "ready"


def test_llm_gateway_smoke_test_endpoint_returns_preview(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.chat.run_llm_smoke_test",
        lambda: type(
            "SmokeTest",
            (),
            {
                "provider": "openai-compatible",
                "model_name": "gpt-4o-mini",
                "configured": True,
                "available": True,
                "status": "ready",
                "message": "LLM 烟雾测试通过。",
                "endpoint": "https://gateway.example.com/v1",
                "sample_question": "北京酒店报销上限是多少？",
                "sample_evidence": "北京酒店报销上限为每晚 650 元。",
                "answer_preview": "根据当前证据，北京酒店报销上限为每晚 650 元。",
                "latency_ms": 15.4,
                "token_usage": {"input_tokens": 12, "output_tokens": 8},
            },
        )(),
    )

    response = client.post("/api/chat/llm-smoke-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["answer_preview"].startswith("根据当前证据")
