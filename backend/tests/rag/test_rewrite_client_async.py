"""Async-path tests for the rewrite + answer LLM clients (P4.2).

Uses ``httpx.MockTransport`` with an injected ``AsyncClient`` so no real
HTTP happens. Parity with the sync tests in
``test_rewrite_client.py`` + ``test_llm_client.py`` is the design goal.
"""

from __future__ import annotations

import json

import httpx

from app.services.llm.client import OpenAICompatiblePolicyAnswerClient
from app.services.llm.rewrite_client import (
    DeterministicRewriteClient,
    OpenAICompatibleRewriteClient,
)


async def test_deterministic_rewrite_async_matches_sync() -> None:
    client = DeterministicRewriteClient()
    assert await client.paraphrase_async("北京酒店", 3) == client.paraphrase("北京酒店", 3)
    assert await client.generate_hyde_document_async("北京酒店") == client.generate_hyde_document(
        "北京酒店"
    )


async def test_openai_rewrite_paraphrase_async_parses_json_array() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "llm-a"
        assert body["messages"][1]["content"].startswith("Question:")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '["变体 A", "变体 B"]',
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleRewriteClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="llm-a",
        )
        variants = await client.paraphrase_async("北京酒店报销上限", 2, async_client=http_client)
    assert variants == ["变体 A", "变体 B"]


async def test_openai_rewrite_paraphrase_async_upstream_error_returns_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleRewriteClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="llm-a",
        )
        # Same degraded semantics as sync: any upstream error → [] (not raise).
        assert await client.paraphrase_async("q", 3, async_client=http_client) == []


async def test_openai_rewrite_hyde_async_returns_document() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "假设回答片段"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleRewriteClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="llm-a",
        )
        doc = await client.generate_hyde_document_async("北京", async_client=http_client)
    assert doc == "假设回答片段"


async def test_openai_rewrite_hyde_async_upstream_error_returns_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "down"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleRewriteClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="llm-a",
        )
        assert await client.generate_hyde_document_async("q", async_client=http_client) == ""


# ---------------------------------------------------------------------------
# Answer client
# ---------------------------------------------------------------------------


async def test_openai_answer_generate_async_parses_response_and_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["messages"][0]["content"] == "你是一个政策助手"
        assert "问题：北京酒店" in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "最终答案。"},
                    }
                ],
                "usage": {"prompt_tokens": 123, "completion_tokens": 7},
                "model": "llm-a",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatiblePolicyAnswerClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="llm-a",
        )
        draft = await client.generate_answer_async(
            question="北京酒店报销上限",
            evidence_snippets=["证据 1", "证据 2"],
            confidence=0.9,
            prompt_template="你是一个政策助手",
            async_client=http_client,
        )

    assert draft.answer == "最终答案。"
    assert draft.confidence == 0.9
    assert draft.model_name == "llm-a"
    assert draft.token_usage == {"input_tokens": 123, "output_tokens": 7}
