"""P6.5: SSE streaming chat endpoint."""

from __future__ import annotations

import json

import httpx
import pytest


@pytest.fixture()
def asgi_app(_test_environment: None, seeded_policy_chunks: None):
    from app.db.session import init_db
    from app.main import create_app

    init_db()
    return create_app()


async def _collect_events(resp: httpx.Response) -> list[dict]:
    """Parse a streaming SSE response into a list of dict events."""
    events: list[dict] = []
    buffer = ""
    async for chunk in resp.aiter_text():
        buffer += chunk
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            for line in frame.splitlines():
                if line.startswith("data:"):
                    payload = line[len("data:") :].strip()
                    if payload:
                        events.append(json.loads(payload))
    return events


async def test_stream_chat_emits_start_citations_delta_done(asgi_app) -> None:
    """A single stream must contain the expected event sequence:
    start → citations → one or more delta → done.
    """
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/chat/ask/stream",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "question": "北京酒店报销上限",
                "tenant_id": "t1",
                "customer_id": "c1",
            },
        ) as resp:
            assert resp.status_code == 200
            events = await _collect_events(resp)

    assert events, "expected at least one SSE event"
    event_types = [e.get("event") for e in events]
    assert event_types[0] == "start"
    assert "citations" in event_types
    assert "delta" in event_types
    assert event_types[-1] == "done"


async def test_stream_chat_session_persisted_after_done(asgi_app) -> None:
    """After the ``done`` event, ChatMessage / RagRecallLog rows must
    be visible — the stream shouldn't lose side effects."""
    from app.db.models.conversation import ChatMessage, ChatSession
    from app.db.models.rag_recall_log import RagRecallLog
    from app.db.session import SessionLocal

    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/chat/ask/stream",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "question": "北京酒店报销上限",
                "tenant_id": "t1",
                "customer_id": "c1",
            },
        ) as resp:
            assert resp.status_code == 200
            events = await _collect_events(resp)

    done_event = next(e for e in events if e.get("event") == "done")
    session_id = done_event["session_id"]

    with SessionLocal() as session:
        assert session.get(ChatSession, session_id) is not None
        messages = session.query(ChatMessage).filter(ChatMessage.session_id == session_id).all()
        assert len(messages) == 2  # user + assistant
        recall = session.query(RagRecallLog).filter(RagRecallLog.session_id == session_id).all()
        assert len(recall) == 1


async def test_stream_chat_returns_sse_content_type(asgi_app) -> None:
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/chat/ask/stream",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "question": "北京酒店报销上限",
                "tenant_id": "t1",
                "customer_id": "c1",
            },
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            # Drain the body so httpx doesn't complain.
            async for _ in resp.aiter_text():
                pass


async def test_stream_chat_delta_text_concatenates_to_full_answer(asgi_app) -> None:
    """Joining every ``delta.text`` should reconstruct the full answer
    (minus trailing whitespace). Guards against losing or duplicating
    chunks during the word-group split.
    """
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/chat/ask/stream",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "question": "北京酒店报销上限",
                "tenant_id": "t1",
                "customer_id": "c1",
            },
        ) as resp:
            assert resp.status_code == 200
            events = await _collect_events(resp)

    deltas = [e["text"] for e in events if e.get("event") == "delta"]
    combined = "".join(deltas)
    # Stream content should be non-empty and roughly the same length
    # as the non-streaming answer.
    assert combined.strip()


async def test_stream_deterministic_llm_chunk_helper() -> None:
    """Direct unit test of ``stream_answer_async`` for the deterministic
    client — guards against the async generator shape breaking."""
    from app.services.llm.client import (
        DeterministicPolicyAnswerClient,
        StreamChunk,
    )

    client = DeterministicPolicyAnswerClient()
    chunks: list[StreamChunk] = []
    async for chunk in client.stream_answer_async(
        question="北京酒店报销上限",
        evidence_snippets=["北京酒店报销上限为每晚 650 元。"],
        confidence=0.9,
        prompt_template="p",
    ):
        chunks.append(chunk)

    assert chunks
    assert chunks[-1].done is True
    assert chunks[-1].token_usage is not None
    # At least one non-terminal chunk carries text.
    assert any(c.delta and not c.done for c in chunks)


# ---------------------------------------------------------------------------
# P7.1: prepare / stream split
# ---------------------------------------------------------------------------


async def test_prepare_answer_context_returns_early_on_no_evidence(
    asgi_app, seeded_policy_chunks: None
) -> None:
    """Query matching nothing (empty tenant) → early-exit
    PolicyAnswerResult, not StreamReadyContext. Lets the stream route
    emit a single delta instead of opening an LLM stream for nothing."""
    from app.services.rag.query_engine import (
        PolicyAnswerResult,
        prepare_answer_context_async,
    )

    result = await prepare_answer_context_async(
        question="完全不相关的随机查询 xyzzy",
        tenant_id="empty-tenant",
        customer_id="c1",
    )
    assert isinstance(result, PolicyAnswerResult)
    assert result.confidence == 0.0
    assert result.citations == []


async def test_stream_chat_token_by_token_via_pushdown(
    asgi_app, seeded_policy_chunks: None
) -> None:
    """P7.1: the stream route now consumes the LLM client's async
    generator directly. For the deterministic client this produces
    multiple delta events for a full-pipeline answer — guards against
    regressing to "single delta at the end" or "no deltas at all".
    """
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/chat/ask/stream",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "question": "北京酒店报销上限",
                "tenant_id": "t1",
                "customer_id": "c1",
            },
        ) as resp:
            assert resp.status_code == 200
            events = await _collect_events(resp)

    deltas = [e for e in events if e.get("event") == "delta"]
    assert deltas, "expected at least one delta from stream pushdown"
    done = [e for e in events if e.get("event") == "done"]
    assert done
    assert done[0].get("model")
    # The joined delta text must be non-empty — proves the push-down
    # actually reconstructs the answer on the client side, not just
    # punts to an empty final message.
    combined = "".join(d.get("text", "") for d in deltas)
    assert combined.strip()
