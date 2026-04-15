from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from app.services.rag.embedding_client import OpenAICompatibleEmbeddingClient, check_embedding_readiness
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


def test_openai_compatible_embedding_client_batches_large_requests() -> None:
    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        batch_inputs = payload["input"]
        requests.append(batch_inputs)
        data = []
        for index, _ in enumerate(batch_inputs):
            value = float(len(requests) * 10 + index)
            data.append(
                {
                    "index": index,
                    "embedding": [value, value + 0.1, value + 0.2, value + 0.3],
                }
            )
        return httpx.Response(200, json={"data": data})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://gateway.example.com/v1",
        api_key="test-key",
        model_name="text-embedding-3-small",
        http_client=http_client,
        batch_size=2,
    )

    vectors = client.embed_texts(["A", "B", "C"], 4)

    assert requests == [["A", "B"], ["C"]]
    assert vectors == [
        [10.0, 10.1, 10.2, 10.3],
        [11.0, 11.1, 11.2, 11.3],
        [20.0, 20.1, 20.2, 20.3],
    ]


def test_openai_compatible_embedding_client_sends_dimensions_and_encoding_format() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "text-embedding-v4"
        assert payload["input"] == ["policy text"]
        assert payload["dimensions"] == 1024
        assert payload["encoding_format"] == "float"
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
        model_name="text-embedding-v4",
        http_client=http_client,
        request_dimensions=1024,
        encoding_format="float",
    )

    vectors = client.embed_texts(["policy text"], 4)

    assert vectors == [[0.1, 0.2, 0.3, 0.4]]


def test_openai_compatible_embedding_client_caps_batch_size_for_dashscope() -> None:
    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(payload["input"])
        data = []
        for index, _ in enumerate(payload["input"]):
            data.append({"index": index, "embedding": [0.1, 0.2, 0.3, 0.4]})
        return httpx.Response(200, json={"data": data})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="test-key",
        model_name="text-embedding-v4",
        http_client=http_client,
        batch_size=16,
    )

    client.embed_texts([str(index) for index in range(11)], 4)

    assert len(requests) == 2
    assert len(requests[0]) == 10
    assert len(requests[1]) == 1


def test_openai_compatible_embedding_client_retries_retryable_gateway_failure() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})

        payload = json.loads(request.content.decode("utf-8"))
        assert payload["input"] == ["鍖椾含閰掑簵鎶ラ攢涓婇檺"]
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
        max_retries=1,
    )

    vectors = client.embed_texts(["鍖椾含閰掑簵鎶ラ攢涓婇檺"], 4)

    assert attempts["count"] == 2
    assert vectors == [[0.1, 0.2, 0.3, 0.4]]


def test_check_embedding_readiness_falls_back_to_embedding_probe_when_models_endpoint_is_unsupported() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/models"):
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if request.url.path.endswith("/embeddings"):
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
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    readiness = check_embedding_readiness(
        provider="openai-compatible",
        base_url="https://gateway.example.com/v1",
        api_key="test-key",
        model_name="text-embedding-v4",
        dimension=4,
        http_client=http_client,
    )

    assert calls == ["GET /v1/models", "POST /v1/embeddings"]
    assert readiness.available is True
    assert readiness.status == "ready"


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
