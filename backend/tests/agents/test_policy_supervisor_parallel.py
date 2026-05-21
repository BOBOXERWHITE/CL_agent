"""P7 Phase A: tests for parallel mixed-domain execution via LangGraph ``Send``.

This pins down the contract of the new ``parallel`` execution mode:

1. **Output parity**: with ``AGENT_MIXED_EXECUTION=parallel`` the
   ``execute_policy_supervisor`` result is structurally identical to
   the legacy ``serial`` mode (same answer text, citations, coverage,
   missing_dimensions, profile_reports, specialist_plan). This is the
   make-or-break invariant — operators must be able to flip the flag
   without seeing user-visible behaviour drift.
2. **True parallelism**: when 3 profiles are planned, the supervisor
   issues 3 ``run_guarded_tool`` invocations concurrently (one per
   worker), instead of serially. We assert this by stubbing the tool
   with an event-emitting fake and checking the "all started before
   any finished" property.
3. **Interrupt propagation**: if any worker reports an incomplete
   coverage, the merged result still triggers ``requires_human_review``
   with the worker's ``missing_dimensions`` prefixed by domain — same
   behaviour as serial mode.

All tests stub ``run_guarded_tool`` to keep the test deterministic
and fast (no real LLM / Milvus call).
"""

from __future__ import annotations

import os
import threading
from typing import Any

import pytest

from app.services.agents.engine import EventType, TimelineEvent
from app.services.agents.policy_supervisor import execute_policy_supervisor
from app.services.agents.state import TimelineStep
from app.services.agents.tool_gateway import GuardedToolResult


def _guarded_result(
    *,
    question: str,
    answer: str,
    confidence: float = 0.9,
    citations: list[dict[str, object]] | None = None,
) -> GuardedToolResult:
    return GuardedToolResult(
        tool_name="policy_search",
        status="completed",
        latency_ms=12,
        input_payload={"question": question},
        output_payload={
            "answer": answer,
            "confidence": confidence,
            "citations": citations or [{"document_id": "doc-1", "chunk_id": answer}],
            "retrieval_mode": "stubbed",
        },
        error=None,
        guardrail_events=[],
        engine_events=[
            TimelineEvent(
                sequence=0,
                event_type=EventType.TOOL_CALL_END,
                node_name="policy_search",
                payload={"question": question},
            )
        ],
    )


@pytest.fixture
def parallel_mode(monkeypatch) -> None:
    """Force AGENT_MIXED_EXECUTION=parallel and rebuild the supervisor graph.

    The graph is compiled at import time so we have to reset the cached
    graph reference for the new flag to take effect.
    """
    monkeypatch.setenv("AGENT_MIXED_EXECUTION", "parallel")
    # Clear lru_cache so the new env var is picked up by get_settings.
    from app.core.config import get_settings

    get_settings.cache_clear()

    # Rebuild graph with new flag
    import app.services.agents.policy_supervisor as supervisor

    supervisor._POLICY_SUPERVISOR_GRAPH = supervisor._build_graph()
    yield
    # Restore default for follow-up tests
    monkeypatch.delenv("AGENT_MIXED_EXECUTION", raising=False)
    get_settings.cache_clear()
    supervisor._POLICY_SUPERVISOR_GRAPH = supervisor._build_graph()


def _build_routing_fake_tool() -> Any:
    """Build a tool stub that returns domain-specific stub answers.

    Same routing as the existing serial test for direct apples-to-apples
    comparison.
    """

    def fake(
        tool_name: str,
        raw_input: dict[str, object],
        *,
        thread_id: str,
        approved: bool = False,
    ) -> GuardedToolResult:
        question = str(raw_input["question"])
        assert tool_name == "policy_search"
        if "酒店" in question or "住宿" in question:
            return _guarded_result(
                question=question,
                answer="酒店域结论：北京 L2 每晚标准 700 元，760 元属于超标。",
            )
        if "机票" in question or "business class" in question.lower() or "舱位" in question:
            return _guarded_result(
                question=question,
                answer="机票域结论：国内 business class 需要额外审批。",
            )
        return _guarded_result(
            question=question,
            answer="报销域结论：发票抬头、税号和进项税需要分别核查。",
        )

    return fake


def test_parallel_mode_produces_same_output_shape_as_serial(
    client, parallel_mode, monkeypatch
) -> None:
    """The headline invariant: flipping the flag must NOT change the
    answer/coverage/missing_dimensions/profile_reports the caller sees."""
    monkeypatch.setattr(
        "app.services.agents.policy_supervisor.run_guarded_tool",
        _build_routing_fake_tool(),
    )

    result = execute_policy_supervisor(
        question=("北京酒店 760 元含早，同时国内机票想订 business class，这张报销单是否合规？"),
        tenant_id="t1",
        customer_id="c1",
        thread_id="thread-parallel-1",
        run_id="run-parallel-1",
        user_id="u1",
        route_name="policy_qa",
        base_timeline=[TimelineStep(node_name="route", status="completed", detail="entered")],
    )

    assert result.requires_human_review is False
    assert result.output["specialist"] == "mixed_policy_supervisor"
    assert result.output["retrieval_trace"]["router"]["domain"] == "mixed"
    assert result.output["specialist_plan"] == [
        "hotel_policy_agent",
        "flight_policy_agent",
        "reimbursement_policy_agent",
    ]
    assert set(result.output["coverage"]["per_domain"]) == {
        "hotel",
        "flight",
        "reimbursement",
    }
    assert result.output["missing_dimensions"] == []
    assert len(result.output["profile_reports"]) == 3
    assert "酒店域结论" in result.output["answer"]
    assert "机票域结论" in result.output["answer"]
    assert "报销域结论" in result.output["answer"]


def test_parallel_mode_actually_runs_workers_concurrently(
    client, parallel_mode, monkeypatch
) -> None:
    """Prove the workers really run in parallel by holding each in a tool
    call until all 3 have started, then releasing — only achievable when
    the supervisor dispatches them concurrently. A serial for-loop would
    deadlock at start_event #1 because tool #2 never runs.
    """
    started_event = threading.Event()
    started_count = threading.Semaphore(0)
    release_event = threading.Event()
    # We expect exactly 3 profiles (hotel + flight + reimbursement) for
    # the question below.
    expected_workers = 3

    started_by_question: list[str] = []
    lock = threading.Lock()

    def fake(
        tool_name: str,
        raw_input: dict[str, object],
        *,
        thread_id: str,
        approved: bool = False,
    ) -> GuardedToolResult:
        question = str(raw_input["question"])
        with lock:
            started_by_question.append(question)
            count = len(started_by_question)
        started_count.release()
        if count >= expected_workers:
            started_event.set()
        # Hold here until the test releases or 2s passes (so a serial
        # supervisor cannot pass the started_event barrier).
        release_event.wait(timeout=2.0)
        if "酒店" in question or "住宿" in question:
            return _guarded_result(question=question, answer="酒店域结论")
        if "机票" in question or "business class" in question.lower() or "舱位" in question:
            return _guarded_result(question=question, answer="机票域结论")
        return _guarded_result(question=question, answer="报销域结论")

    monkeypatch.setattr(
        "app.services.agents.policy_supervisor.run_guarded_tool",
        fake,
    )

    # Run the supervisor in a worker thread so we can release the barrier
    # from the test thread once all workers have started.
    result_holder: dict[str, Any] = {}

    def driver() -> None:
        result_holder["result"] = execute_policy_supervisor(
            question=("北京酒店 760 元含早，同时国内机票想订 business class，这张报销单是否合规？"),
            tenant_id="t1",
            customer_id="c1",
            thread_id="thread-parallel-concurrent",
            run_id="run-parallel-concurrent",
            user_id="u1",
            route_name="policy_qa",
            base_timeline=[],
        )

    t = threading.Thread(target=driver, daemon=True)
    t.start()
    # Wait up to 3s for all 3 workers to enter the tool body
    started_in_parallel = started_event.wait(timeout=3.0)
    # Even if parallel mode is incorrectly wired and tests time out, give
    # the driver a chance to finish gracefully so the test isn't a hang.
    release_event.set()
    t.join(timeout=10.0)

    assert started_in_parallel, (
        f"workers did not all start in parallel within 3s; "
        f"only {len(started_by_question)} of {expected_workers} entered the tool body — "
        f"check that AGENT_MIXED_EXECUTION=parallel actually fans out via Send"
    )
    # Output parity sanity check
    assert "result" in result_holder
    assert result_holder["result"].output["specialist"] == "mixed_policy_supervisor"


def test_parallel_mode_propagates_partial_missing_dimensions(
    client, parallel_mode, monkeypatch
) -> None:
    """If one worker reports incomplete coverage the merged result must
    still set requires_human_review with the missing dimensions
    prefixed by domain — same shape as serial mode's interrupt block."""

    def fake(
        tool_name: str,
        raw_input: dict[str, object],
        *,
        thread_id: str,
        approved: bool = False,
    ) -> GuardedToolResult:
        question = str(raw_input["question"])
        if "审批条件" in question or "审批要求" in question:
            # Force the flight approval dimension to be incomplete
            return _guarded_result(
                question=question,
                answer="机票审批证据不足。",
                confidence=0.05,
                citations=[],
            )
        if "机票" in question or "business class" in question.lower() or "舱位" in question:
            return _guarded_result(question=question, answer="机票域结论：默认规则已找到。")
        if "酒店" in question or "住宿" in question:
            return _guarded_result(question=question, answer="酒店域结论：房费标准已找到。")
        return _guarded_result(question=question, answer="报销域结论：基础报销规则已找到。")

    monkeypatch.setattr(
        "app.services.agents.policy_supervisor.run_guarded_tool",
        fake,
    )

    result = execute_policy_supervisor(
        question=("北京酒店 760 元，同时国内机票想订 business class，这张报销单是否合规？"),
        tenant_id="t1",
        customer_id="c1",
        thread_id="thread-parallel-interrupt",
        run_id="run-parallel-interrupt",
        user_id="u1",
        route_name="policy_qa",
        base_timeline=[],
    )

    assert result.requires_human_review is True
    assert result.status == "needs_review"
    assert "flight.approval_requirement" in result.output["missing_dimensions"]
    assert result.output["interrupt"] is not None
    assert result.output["interrupt"]["kind"] == "completeness_review"


def test_default_mode_remains_serial_when_flag_unset() -> None:
    """The flag defaults to 'serial' so production deployments are not
    silently flipped to parallel just by upgrading code."""
    # Clear any per-test env override
    os.environ.pop("AGENT_MIXED_EXECUTION", None)
    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    assert settings.agent_mixed_execution == "serial"
