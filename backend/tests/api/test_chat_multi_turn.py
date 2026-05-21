"""End-to-end test for the P11 multi-turn pipeline.

Verifies two structural invariants:

1. ``/api/chat/ask`` carries the same ``thread_id`` across two requests
   so the second turn can see the first.
2. The OpenAI-compatible client receives the prior turn in its
   ``messages`` array (system → prior_user → prior_assistant → current),
   not just the current question — i.e. the LLM actually has the context
   it needs to answer "那广州呢？" after "北京住宿标准是多少？".
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest


@pytest.fixture()
def asgi_app(_test_environment: None) -> object:
    from app.main import create_app

    return create_app()


async def test_second_turn_carries_prior_turn_to_llm(
    asgi_app,
    seeded_multilingual_policy_chunks: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Capture every request the OpenAI-compatible client emits so we can
    # assert on the messages array of the SECOND call. Force the engine
    # onto the real http client by setting an OpenAI-style provider, and
    # back the client with a MockTransport that returns canned answers.
    captured_payloads: list[dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "回答内容"}, "index": 0}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                "model": "test-model",
            },
        )

    transport = httpx.MockTransport(_handler)

    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_API_BASE_URL", "http://fake-llm/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL_NAME", "test-model")
    # Make sure CRAG doesn't add extra LLM calls and confuse the assertion.
    monkeypatch.setenv("CRAG_ENABLED", "false")
    monkeypatch.setenv("CHAT_HISTORY_MAX_TURNS", "5")

    from app.core.config import get_settings
    from app.services.rag import async_http_client as ahc

    get_settings.cache_clear()

    # Replace the shared async client so all OpenAI-compatible calls flow
    # through our MockTransport for this test. The module-level singleton
    # is ``_client``; nulling and re-seeding lets get_async_http_client()
    # hand out our mock instead of building a real one.
    ahc._client = httpx.AsyncClient(transport=transport)  # type: ignore[attr-defined]

    try:
        transport_asgi = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(
            transport=transport_asgi, base_url="http://testserver"
        ) as client:
            headers = {"Authorization": "Bearer admin-token"}

            first = await client.post(
                "/api/chat/ask",
                headers=headers,
                json={
                    "question": "北京酒店报销上限是多少？",
                    "tenant_id": "t1",
                    "customer_id": "c1",
                },
            )
            assert first.status_code == 200, first.text
            thread_id = first.json()["thread_id"]
            assert thread_id

            # The seeded fixture only covers Beijing + Shanghai, so the
            # second question must lexically match one of those to avoid
            # the no-evidence early exit (which would skip the LLM answer
            # call entirely and defeat the assertion below).
            second = await client.post(
                "/api/chat/ask",
                headers=headers,
                json={
                    "question": "Shanghai hotel reimbursement cap 是多少？",
                    "tenant_id": "t1",
                    "customer_id": "c1",
                    "thread_id": thread_id,
                },
            )
            assert second.status_code == 200, second.text
            assert second.json()["thread_id"] == thread_id
    finally:
        await ahc._client.aclose()  # type: ignore[attr-defined]
        ahc._client = None  # type: ignore[attr-defined]
        get_settings.cache_clear()

    # Per turn the engine emits multiple LLM calls — query rewrite
    # (paraphrase / HyDE) and the final answer generation. We only care
    # about the *answer* calls; those are the ones whose trailing user
    # message contains the canonical evidence-grounded prompt prefix.
    answer_payloads = [
        payload
        for payload in captured_payloads
        if payload["messages"]
        and payload["messages"][-1]["role"] == "user"
        and "请基于给定证据回答问题" in payload["messages"][-1]["content"]
    ]
    # Per turn the engine emits 2–3 LLM calls (paraphrase, optional HyDE,
    # final answer); we only assert on the answer-shaped ones.
    assert len(answer_payloads) >= 2, (
        f"expected at least 2 answer calls, captured={len(answer_payloads)}"
    )
    second_answer = answer_payloads[-1]
    roles = [m["role"] for m in second_answer["messages"]]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    # At least one user→assistant pair must appear *between* system and
    # the trailing user question.
    interior = roles[1:-1]
    assert "user" in interior and "assistant" in interior, (
        f"prior turn missing from second answer LLM call. roles={roles}"
    )

    # And the prior user content must literally be the first turn's question.
    prior_user_contents = [
        m["content"] for m in second_answer["messages"][1:-1] if m["role"] == "user"
    ]
    assert any("北京酒店报销上限是多少" in c for c in prior_user_contents), (
        f"prior user message lost. interior_user={prior_user_contents}"
    )
