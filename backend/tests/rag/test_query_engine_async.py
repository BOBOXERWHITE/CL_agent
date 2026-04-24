"""Async-path tests for the query engine (P4.2).

The sync ``answer_policy_question`` and its async twin
``answer_policy_question_async`` MUST return the same
``PolicyAnswerResult`` for the same inputs — we assert this explicitly so
the two paths can't silently drift. Concurrency behaviour is pinned with
``asyncio.gather`` + deterministic providers (no real HTTP needed).
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.rag.query_engine import (
    answer_policy_question,
    answer_policy_question_async,
)


async def test_async_matches_sync_for_same_inputs(seeded_policy_chunks: None) -> None:
    """Parity pin: the two code paths must agree on answer / confidence /
    citation count. If this breaks it's almost always because a new
    code path in the sync version wasn't mirrored async-side.
    """
    question = "北京酒店报销上限"
    sync_result = answer_policy_question(question=question, tenant_id="t1", customer_id="c1")
    async_result = await answer_policy_question_async(
        question=question, tenant_id="t1", customer_id="c1"
    )

    assert async_result.answer == sync_result.answer
    assert async_result.confidence == sync_result.confidence
    assert len(async_result.citations) == len(sync_result.citations)
    assert async_result.prompt_template_id == sync_result.prompt_template_id


async def test_async_concurrent_requests_share_work(seeded_policy_chunks: None) -> None:
    """Fire 5 concurrent ``answer_policy_question_async`` calls. They
    use the same deterministic provider + identical input so they land
    on the cache path after the first; total wall-clock should stay
    well under 5× single-request time.

    The exact ratio is fuzzy (depends on scheduler + thread pool), so
    we just require "noticeably faster than serial" — 3× is a generous
    ceiling that won't flake on slow CI.
    """
    question = "上海酒店报销上限"

    serial_start = asyncio.get_event_loop().time()
    await answer_policy_question_async(question=question, tenant_id="t1", customer_id="c1")
    serial_elapsed = asyncio.get_event_loop().time() - serial_start

    parallel_start = asyncio.get_event_loop().time()
    await asyncio.gather(
        *(
            answer_policy_question_async(question=question, tenant_id="t1", customer_id="c1")
            for _ in range(5)
        )
    )
    parallel_elapsed = asyncio.get_event_loop().time() - parallel_start

    # 5 parallel calls should finish in less than 3× single-call time.
    # This is a loose bound — real async IO sees ~1.1×; we leave ample
    # headroom for the sync retrieval path running on a shared thread pool.
    assert parallel_elapsed < max(serial_elapsed * 3.0, 0.5)


async def test_async_no_evidence_path(seeded_policy_chunks: None) -> None:
    """A query with zero matching chunks must land on the "not enough
    evidence" fallback, async side identical to sync.
    """
    question = "完全不相关的随机查询 xyzzy"
    sync_result = answer_policy_question(
        question=question, tenant_id="empty-tenant", customer_id="c1"
    )
    async_result = await answer_policy_question_async(
        question=question, tenant_id="empty-tenant", customer_id="c1"
    )
    assert async_result.answer == sync_result.answer
    assert async_result.confidence == sync_result.confidence
    assert async_result.citations == [] == sync_result.citations


async def test_async_handles_empty_question_gracefully(seeded_policy_chunks: None) -> None:
    """Empty/whitespace questions are API-level validation errors normally,
    but the engine itself shouldn't crash if one slips through — both
    paths must produce the same shape.
    """
    try:
        sync_result = answer_policy_question(question=" ", tenant_id="t1", customer_id="c1")
    except Exception as exc:
        # If sync raises, async MUST raise the same way (same type).
        with pytest.raises(type(exc)):
            await answer_policy_question_async(question=" ", tenant_id="t1", customer_id="c1")
        return

    async_result = await answer_policy_question_async(
        question=" ", tenant_id="t1", customer_id="c1"
    )
    assert async_result.answer == sync_result.answer


async def test_rewrite_async_matches_sync_for_deterministic_provider() -> None:
    """Multi-query rewrite: deterministic client returns the same thing
    sync and async, so the engine's two paths start from identical state.
    """
    from app.services.rag.query_rewriter import (
        rewrite_query_multi,
        rewrite_query_multi_async,
    )

    question = "北京酒店报销上限"
    sync_result = rewrite_query_multi(question)
    async_result = await rewrite_query_multi_async(question)

    assert async_result.original_query == sync_result.original_query
    assert async_result.expanded_query == sync_result.expanded_query
    assert async_result.applied_rules == sync_result.applied_rules
    assert async_result.llm_variants == sync_result.llm_variants
    assert async_result.hyde_document == sync_result.hyde_document
