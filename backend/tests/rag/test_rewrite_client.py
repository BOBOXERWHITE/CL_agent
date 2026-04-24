"""Unit tests for the LLM rewrite client.

Uses ``httpx.MockTransport`` to simulate upstream responses.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.llm.rewrite_client import (
    DeterministicRewriteClient,
    OpenAICompatibleRewriteClient,
    RewriteClientConfigError,
    get_rewrite_client,
)


def test_deterministic_client_returns_canned_outputs() -> None:
    client = DeterministicRewriteClient()
    assert client.paraphrase("anything", 3) == []
    assert client.generate_hyde_document("foo") == "(deterministic HyDE) foo"


def test_openai_client_rejects_missing_config() -> None:
    with pytest.raises(RewriteClientConfigError):
        OpenAICompatibleRewriteClient(base_url="", api_key="k", model_name="m")
    with pytest.raises(RewriteClientConfigError):
        OpenAICompatibleRewriteClient(base_url="https://x/v1", api_key="", model_name="m")
    with pytest.raises(RewriteClientConfigError):
        OpenAICompatibleRewriteClient(base_url="https://x/v1", api_key="k", model_name="")


def test_openai_paraphrase_parses_json_array() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '["alt 1","alt 2"]'}}]},
        )

    transport = httpx.MockTransport(handler)
    client = OpenAICompatibleRewriteClient(
        base_url="https://api.x/v1",
        api_key="sk",
        model_name="gpt-x",
        http_client=httpx.Client(transport=transport),
    )
    assert client.paraphrase("q", 2) == ["alt 1", "alt 2"]


def test_openai_paraphrase_strips_code_fences() -> None:
    payload = '```json\n["a","b"]\n```'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": payload}}]})

    client = OpenAICompatibleRewriteClient(
        base_url="https://api.x/v1",
        api_key="sk",
        model_name="gpt-x",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.paraphrase("q", 2) == ["a", "b"]


def test_openai_paraphrase_falls_back_to_line_split() -> None:
    """Non-JSON response: split by newline and trim bullet chars."""
    payload = "- line one\n* line two\n  line three"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": payload}}]})

    client = OpenAICompatibleRewriteClient(
        base_url="https://api.x/v1",
        api_key="sk",
        model_name="gpt-x",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    out = client.paraphrase("q", 5)
    assert out == ["line one", "line two", "line three"]


def test_openai_paraphrase_http_error_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = OpenAICompatibleRewriteClient(
        base_url="https://api.x/v1",
        api_key="sk",
        model_name="gpt-x",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.paraphrase("q", 2) == []


def test_openai_hyde_returns_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps({"choices": [{"message": {"content": "hypothetical answer."}}]})
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    client = OpenAICompatibleRewriteClient(
        base_url="https://api.x/v1",
        api_key="sk",
        model_name="gpt-x",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.generate_hyde_document("what is X") == "hypothetical answer."


def test_openai_hyde_http_error_returns_empty_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "gateway"})

    client = OpenAICompatibleRewriteClient(
        base_url="https://api.x/v1",
        api_key="sk",
        model_name="gpt-x",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.generate_hyde_document("q") == ""


def test_factory_falls_back_to_deterministic_when_llm_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_API_BASE_URL", "")  # missing
    monkeypatch.setenv("LLM_API_KEY", "sk")
    monkeypatch.setenv("LLM_MODEL_NAME", "gpt-x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    client = get_rewrite_client()
    assert isinstance(client, DeterministicRewriteClient)
    get_settings.cache_clear()


def test_factory_builds_openai_client_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_API_BASE_URL", "https://api.x/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-real")
    monkeypatch.setenv("LLM_MODEL_NAME", "gpt-x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    client = get_rewrite_client()
    assert isinstance(client, OpenAICompatibleRewriteClient)
    assert client.base_url == "https://api.x/v1"
    get_settings.cache_clear()


def test_factory_returns_deterministic_for_deterministic_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert isinstance(get_rewrite_client(), DeterministicRewriteClient)
    get_settings.cache_clear()
