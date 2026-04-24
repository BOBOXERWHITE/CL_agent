"""P6.5: OpenAI-compatible streaming client tests."""

from __future__ import annotations

import json

import httpx

from app.services.llm.client import (
    DeterministicPolicyAnswerClient,
    OpenAICompatiblePolicyAnswerClient,
)


async def test_openai_stream_reads_data_frames_and_finishes_on_done() -> None:
    """Feed a canned SSE transcript and assert the client yields one
    chunk per ``data:`` line until it sees ``[DONE]``."""

    async def handler(request: httpx.Request) -> httpx.Response:
        frames = [
            b'data: {"choices": [{"delta": {"content": "Hello "}}], "model": "m"}\n\n',
            b'data: {"choices": [{"delta": {"content": "world"}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "!"}}]}\n\n',
            b'data: {"usage": {"prompt_tokens": 10, "completion_tokens": 3}}\n\n',
            b"data: [DONE]\n\n",
        ]
        return httpx.Response(200, content=b"".join(frames))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatiblePolicyAnswerClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="m",
        )
        chunks = []
        async for chunk in client.stream_answer_async(
            question="q",
            evidence_snippets=["e"],
            confidence=0.9,
            prompt_template="p",
            async_client=http_client,
        ):
            chunks.append(chunk)

    content_chunks = [c for c in chunks if not c.done]
    final = [c for c in chunks if c.done]
    assert [c.delta for c in content_chunks] == ["Hello ", "world", "!"]
    assert len(final) == 1
    assert final[0].token_usage == {"input_tokens": 10, "output_tokens": 3}


async def test_openai_stream_ignores_malformed_json_lines() -> None:
    """Garbage JSON frames must not crash the consumer — just skip them."""

    async def handler(request: httpx.Request) -> httpx.Response:
        frames = [
            b"data: not-json\n\n",
            b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]
        return httpx.Response(200, content=b"".join(frames))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatiblePolicyAnswerClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="m",
        )
        chunks = []
        async for chunk in client.stream_answer_async(
            question="q",
            evidence_snippets=["e"],
            confidence=0.9,
            prompt_template="p",
            async_client=http_client,
        ):
            chunks.append(chunk)

    # Only the valid "ok" delta + the terminal chunk.
    assert len([c for c in chunks if not c.done]) == 1


async def test_openai_stream_sends_stream_flag_in_body() -> None:
    """Streaming must set ``stream=true`` in the request body — the
    upstream needs this to switch into SSE mode."""
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatiblePolicyAnswerClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="m",
        )
        async for _ in client.stream_answer_async(
            question="q",
            evidence_snippets=["e"],
            confidence=0.9,
            prompt_template="p",
            async_client=http_client,
        ):
            pass

    assert captured
    body = json.loads(captured[0].content.decode("utf-8"))
    assert body["stream"] is True
    assert body["model"] == "m"


async def test_openai_stream_4xx_raises_on_start() -> None:
    """A 4xx on the SSE open must raise before any chunk is yielded —
    we fail fast instead of silently returning an empty stream."""
    import pytest

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatiblePolicyAnswerClient(
            base_url="https://g.example.com/v1",
            api_key="k",
            model_name="m",
        )
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in client.stream_answer_async(
                question="q",
                evidence_snippets=["e"],
                confidence=0.9,
                prompt_template="p",
                async_client=http_client,
            ):
                pass


async def test_deterministic_stream_matches_generate_answer_total() -> None:
    """The deterministic client's stream joined should equal the
    non-streaming answer — proof the chunking doesn't drop content."""
    client = DeterministicPolicyAnswerClient()
    draft = client.generate_answer(
        question="北京酒店报销上限",
        evidence_snippets=["北京酒店报销上限为每晚 650 元。"],
        confidence=0.9,
        prompt_template="p",
    )
    pieces: list[str] = []
    async for chunk in client.stream_answer_async(
        question="北京酒店报销上限",
        evidence_snippets=["北京酒店报销上限为每晚 650 元。"],
        confidence=0.9,
        prompt_template="p",
    ):
        if not chunk.done:
            pieces.append(chunk.delta)
    # Rejoin — strip trailing whitespace from each piece since we
    # inserted spaces between groups.
    combined = "".join(pieces).strip()
    assert combined == draft.answer.strip()
