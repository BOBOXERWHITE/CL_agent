from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from app.services.rag.embedding_client import OpenAICompatibleEmbeddingClient
from app.services.rag.index_builder import build_vector_records


def test_openai_compatible_embedding_client_parses_gateway_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "text-embedding-3-small"
        assert payload["input"] == ["北京酒店报销上限"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "index": 0,
                        "embedding": [0.1, 0.2, 0.3, 0.4],
                    }
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://gateway.example.com/v1",
        api_key="test-key",
        model_name="text-embedding-3-small",
        http_client=http_client,
    )

    vectors = client.embed_texts(["北京酒店报销上限"], 4)

    assert vectors == [[0.1, 0.2, 0.3, 0.4]]


def test_build_vector_records_uses_embedding_client(monkeypatch) -> None:
    chunk = SimpleNamespace(
        id="chunk-1",
        document_id="doc-1",
        tenant_id="t1",
        customer_id="c1",
        content="北京酒店报销上限为每晚 650 元。",
    )

    monkeypatch.setattr(
        "app.services.rag.index_builder.texts_to_embeddings",
        lambda texts, dimension: [[0.11, 0.22, 0.33, 0.44] for _ in texts],
    )
    monkeypatch.setenv("EMBEDDING_DIMENSION", "4")

    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        records = build_vector_records([chunk])
    finally:
        get_settings.cache_clear()

    assert records[0].embedding == [0.11, 0.22, 0.33, 0.44]
