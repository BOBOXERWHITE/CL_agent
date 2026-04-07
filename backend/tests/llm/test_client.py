from __future__ import annotations

import json

import httpx

from app.services.llm.client import (
    DeterministicPolicyAnswerClient,
    OpenAICompatiblePolicyAnswerClient,
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
