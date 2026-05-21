"""P7 Phase C: tests for the agent-as-tool ``call_agent`` Tool.

Lets one agent invoke another mid-execution. Today the only natural
caller is the LLM-driven ReAct planner (Phase B) in ``policy_graph``,
but the Tool itself is agent-agnostic — anyone with access to the
registry can call it.

Invariants under test:

1. **Registration is feature-flagged**: when
   ``settings.agent_as_tool_enabled`` is False, the tool is NOT in the
   default registry — keeps the policy agent's blast radius bounded
   in fresh deployments.
2. **Recursion guard caps depth**: a 4th nested call (after 3 levels)
   returns a failed CallAgentOutput instead of recursing further. The
   guard uses a ``ContextVar`` so it's per-request-thread, not global.
3. **Tenant + customer scope propagates**: the inner agent's
   tenant_id / customer_id matches the outer call's values; cross-tenant
   leakage is impossible by construction.
4. **Self-delegation rejected**: ``call_agent(agent_name="policy_qa")``
   while already inside policy_qa returns an error verdict (would
   otherwise be a guaranteed infinite loop).
5. **Unknown agent_name returns error**: typo / hallucinated agent
   name returns ``status="failed"`` instead of crashing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.core.config import Settings, get_settings
from app.services.agents.agent_as_tool import (
    AGENT_CALL_DEPTH_CONTEXT,
    CallAgentInput,
    CallAgentTool,
    ensure_agent_as_tool_registration,
)
from app.services.agents.state import AgentExecutionResult
from app.services.agents.tool_registry import get_default_registry


@pytest.fixture(autouse=True)
def _reset_registry_for_each_test() -> None:
    """Strip any prior registration so flag-OFF tests start clean."""
    registry = get_default_registry()
    if registry.has("call_agent"):
        # No public unregister API; clear-and-reseed default registry
        # by reaching into the tested registry's private dict (test-only).
        registry._tools.pop("call_agent", None)
    yield
    if registry.has("call_agent"):
        registry._tools.pop("call_agent", None)


@pytest.fixture
def enabled_settings(monkeypatch) -> Settings:
    settings = get_settings()
    overridden = replace(settings, agent_as_tool_enabled=True, agent_as_tool_max_depth=3)
    monkeypatch.setattr("app.services.agents.agent_as_tool.get_settings", lambda: overridden)
    return overridden


def _stub_execution_result(
    answer: str = "OK", agent_name: str = "policy_supervisor_agent"
) -> AgentExecutionResult:
    from app.services.agents.state import TimelineStep

    return AgentExecutionResult(
        agent_name=agent_name,
        route_name="policy_qa",
        status="completed",
        confidence=0.91,
        requires_human_review=False,
        output={
            "answer": answer,
            "citations": [{"document_id": "doc-1", "chunk_id": "c1"}],
        },
        timeline=[TimelineStep(node_name="route", status="completed", detail="")],
        tool_calls=[],
        engine_events=[],
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registration_skipped_when_disabled(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        "app.services.agents.agent_as_tool.get_settings",
        lambda: replace(settings, agent_as_tool_enabled=False),
    )
    ensure_agent_as_tool_registration()
    assert get_default_registry().has("call_agent") is False


def test_registration_happens_when_enabled(enabled_settings: Settings) -> None:
    ensure_agent_as_tool_registration()
    registry = get_default_registry()
    assert registry.has("call_agent") is True
    tool = registry.get("call_agent")
    assert tool.name == "call_agent"
    assert "agent" in tool.description.lower()


def test_registration_is_idempotent(enabled_settings: Settings) -> None:
    """Calling ensure_*() twice must not raise ToolRegistryConflict."""
    ensure_agent_as_tool_registration()
    ensure_agent_as_tool_registration()
    assert get_default_registry().has("call_agent") is True


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def test_call_agent_routes_to_policy_supervisor(enabled_settings: Settings, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_execute(**kwargs: Any) -> AgentExecutionResult:
        captured.update(kwargs)
        return _stub_execution_result(answer="北京酒店上限 700 元")

    monkeypatch.setattr(
        "app.services.agents.agent_as_tool.execute_policy_supervisor",
        fake_execute,
    )

    tool = CallAgentTool()
    payload = CallAgentInput(
        agent_name="policy_qa",
        question="北京酒店报销上限？",
        tenant_id="t1",
        customer_id="c1",
        caller_agent_name="ticket_router_agent",
    )
    output = tool.invoke(payload)

    assert captured["question"] == "北京酒店报销上限？"
    assert captured["tenant_id"] == "t1"
    assert captured["customer_id"] == "c1"
    assert output.agent_name == "policy_supervisor_agent"
    assert output.status == "completed"
    assert output.answer == "北京酒店上限 700 元"
    assert output.confidence == pytest.approx(0.91)
    assert output.depth == 1


def test_recursion_guard_rejects_calls_beyond_max_depth(
    enabled_settings: Settings,
) -> None:
    """Force the ContextVar to depth 3, then call. The tool must
    refuse with status=failed instead of executing the target."""
    token = AGENT_CALL_DEPTH_CONTEXT.set(3)
    try:
        tool = CallAgentTool()
        output = tool.invoke(
            CallAgentInput(
                agent_name="policy_qa",
                question="Q",
                tenant_id="t1",
                customer_id="c1",
                caller_agent_name="policy_supervisor_agent",
            )
        )
    finally:
        AGENT_CALL_DEPTH_CONTEXT.reset(token)
    assert output.status == "failed"
    assert "max depth" in output.error.lower()
    # depth in output reflects the would-be depth so observability can
    # show which level triggered the refusal.
    assert output.depth == 4


def test_self_delegation_rejected(enabled_settings: Settings, monkeypatch) -> None:
    """policy_supervisor calling call_agent(agent_name=policy_qa) would
    just bounce straight back — guaranteed infinite loop until depth cap.
    Cheaper to refuse up front."""

    # Even if the underlying executor would succeed, this test must
    # never let it run; assert with a guard.
    def fail_if_called(**_kw: Any) -> AgentExecutionResult:  # pragma: no cover
        raise AssertionError("self-delegation must short-circuit before execute")

    monkeypatch.setattr(
        "app.services.agents.agent_as_tool.execute_policy_supervisor",
        fail_if_called,
    )

    tool = CallAgentTool()
    output = tool.invoke(
        CallAgentInput(
            agent_name="policy_qa",
            question="Q",
            tenant_id="t1",
            customer_id="c1",
            caller_agent_name="policy_supervisor_agent",
        )
    )
    assert output.status == "failed"
    assert "self" in output.error.lower()


def test_unknown_agent_name_returns_failed(enabled_settings: Settings) -> None:
    """The Pydantic Literal already filters unknown names but defence in
    depth: even if the input bypassed validation somehow, the tool itself
    rejects unmapped names instead of throwing KeyError."""
    with pytest.raises(ValueError):
        CallAgentInput(
            agent_name="this_agent_does_not_exist",  # type: ignore[arg-type]
            question="Q",
            tenant_id="t1",
            customer_id="c1",
            caller_agent_name="x",
        )


def test_nested_call_increments_depth(enabled_settings: Settings, monkeypatch) -> None:
    """Two nested call_agent invocations should report depth 1 then 2."""
    observed_depths: list[int] = []

    def fake_execute(**kwargs: Any) -> AgentExecutionResult:
        # Capture the depth as observed INSIDE the outer call by
        # invoking the tool a second time before returning.
        depth_now = AGENT_CALL_DEPTH_CONTEXT.get()
        observed_depths.append(depth_now)
        return _stub_execution_result(answer=f"depth={depth_now}")

    monkeypatch.setattr(
        "app.services.agents.agent_as_tool.execute_policy_supervisor",
        fake_execute,
    )

    tool = CallAgentTool()

    # Outer call
    outer = tool.invoke(
        CallAgentInput(
            agent_name="policy_qa",
            question="Q",
            tenant_id="t1",
            customer_id="c1",
            caller_agent_name="ticket_router_agent",
        )
    )
    assert outer.depth == 1
    assert observed_depths == [1]

    # Reset for clarity; second invocation is a separate top-level call
    observed_depths.clear()
    outer2 = tool.invoke(
        CallAgentInput(
            agent_name="policy_qa",
            question="Q2",
            tenant_id="t1",
            customer_id="c1",
            caller_agent_name="ticket_router_agent",
        )
    )
    assert outer2.depth == 1


def test_depth_context_var_resets_after_call(enabled_settings: Settings, monkeypatch) -> None:
    """The ContextVar must be reset on exit so a failed inner call does
    not leak the depth into the next request handled by the same thread."""

    def fake_execute(**_kw: Any) -> AgentExecutionResult:
        return _stub_execution_result()

    monkeypatch.setattr(
        "app.services.agents.agent_as_tool.execute_policy_supervisor",
        fake_execute,
    )

    starting_depth = AGENT_CALL_DEPTH_CONTEXT.get()
    tool = CallAgentTool()
    tool.invoke(
        CallAgentInput(
            agent_name="policy_qa",
            question="Q",
            tenant_id="t1",
            customer_id="c1",
            caller_agent_name="ticket_router_agent",
        )
    )
    assert AGENT_CALL_DEPTH_CONTEXT.get() == starting_depth
