from __future__ import annotations

import json

import httpx

from app.services.llm.client import (
    DeterministicPolicyAnswerClient,
    check_llm_readiness,
    OpenAICompatiblePolicyAnswerClient,
    run_llm_smoke_test,
    get_policy_answer_client,
)


def test_openai_compatible_policy_client_parses_gateway_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-4o-mini"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "content": "根据当前证据，北京酒店报销上限为每晚 650 元。"
                        }
                    }
                ],
                "usage": {"prompt_tokens": 42, "completion_tokens": 16},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatiblePolicyAnswerClient(
        base_url="https://gateway.example.com/v1",
        api_key="test-key",
        model_name="gpt-4o-mini",
        http_client=http_client,
    )

    result = client.generate_answer(
        question="北京酒店报销上限是多少？",
        evidence_snippets=["北京酒店报销上限为每晚 650 元。"],
        confidence=0.64,
        prompt_template="请基于证据回答。",
    )

    assert result.answer == "根据当前证据，北京酒店报销上限为每晚 650 元。"
    assert result.model_name == "gpt-4o-mini"
    assert result.token_usage == {"input_tokens": 42, "output_tokens": 16}


def test_policy_answer_client_falls_back_without_gateway_credentials(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_BASE_URL", "https://gateway.example.com/v1")

    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        client = get_policy_answer_client()
    finally:
        get_settings.cache_clear()

    assert isinstance(client, DeterministicPolicyAnswerClient)


def test_check_llm_readiness_reports_gateway_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o-mini"},
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    readiness = check_llm_readiness(
        provider="openai-compatible",
        base_url="https://gateway.example.com/v1",
        api_key="test-key",
        model_name="gpt-4o-mini",
        http_client=http_client,
    )

    assert readiness.available is True
    assert readiness.status == "ready"
    assert "gpt-4o-mini" in readiness.message


def test_check_llm_readiness_falls_back_to_chat_probe_when_models_endpoint_is_unsupported() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/models"):
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-v3-2-251201",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    readiness = check_llm_readiness(
        provider="openai-compatible",
        base_url="https://gateway.example.com/v1",
        api_key="test-key",
        model_name="deepseek-v3-2-251201",
        http_client=http_client,
    )

    assert calls == ["GET /v1/models", "POST /v1/chat/completions"]
    assert readiness.available is True
    assert readiness.status == "ready"
    assert "deepseek-v3-2-251201" in readiness.message


def test_run_llm_smoke_test_returns_answer_preview_and_token_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "content": "根据当前证据，北京酒店报销上限为每晚 650 元。"
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    result = run_llm_smoke_test(
        provider="openai-compatible",
        base_url="https://gateway.example.com/v1",
        api_key="test-key",
        model_name="gpt-4o-mini",
        http_client=http_client,
    )

    assert result.available is True
    assert result.status == "ready"
    assert result.answer_preview.startswith("根据当前证据")
    assert result.token_usage == {"input_tokens": 12, "output_tokens": 8}
