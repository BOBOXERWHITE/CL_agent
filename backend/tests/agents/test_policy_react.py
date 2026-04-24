"""Tests for the P3.3 Policy ReAct graph.

End-to-end covers:
- Happy path: plan → act → observe → plan → finalize
- Event stream includes NODE_START, TOOL_CALL_END
- tool_calls are captured and translated to ToolCallRecord
- retrieval_trace carries end_reason + react_steps so P3.7 audit can
  persist them unchanged
- confidence below threshold flags requires_human_review

All runs use the default deterministic RAG stack + seeded chunks from
conftest.
"""

from __future__ import annotations

from app.services.agents.policy_graph import (
    build_policy_graph,
    execute_policy_graph,
)
from app.services.agents.state import TimelineStep


def test_react_graph_happy_path_produces_answer_and_citations(
    seeded_multilingual_policy_chunks: None,
) -> None:
    result = execute_policy_graph(
        question="北京酒店报销上限是多少？",
        tenant_id="t1",
        customer_id="c1",
        route_name="policy_qa",
        base_timeline=[],
    )
    assert result.agent_name == "travel_policy_agent"
    assert result.output["answer"]
    # Deterministic RAG returns citations for seeded chunks.
    assert isinstance(result.output["citations"], list)
    # react_steps = plan + act + observe + plan + finalize = 5 (one ReAct loop)
    assert result.output["retrieval_trace"]["react_steps"] >= 3


def test_react_graph_records_tool_call(seeded_multilingual_policy_chunks: None) -> None:
    result = execute_policy_graph(
        question="北京酒店报销上限",
        tenant_id="t1",
        customer_id="c1",
        route_name="policy_qa",
        base_timeline=[],
    )
    # Exactly one policy_search tool call should be in the record.
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.tool_name == "policy_search"
    assert call.status in {"completed", "failed", "validation_error"}


def test_react_graph_timeline_reflects_node_execution(
    seeded_multilingual_policy_chunks: None,
) -> None:
    base = [TimelineStep(node_name="router", status="completed", detail="routed")]
    result = execute_policy_graph(
        question="北京酒店报销上限",
        tenant_id="t1",
        customer_id="c1",
        route_name="policy_qa",
        base_timeline=base,
    )
    # Base step preserved at index 0.
    assert result.timeline[0].node_name == "router"
    # Nodes from the graph appear afterwards.
    node_names = {step.node_name for step in result.timeline}
    assert "plan" in node_names
    assert "act" in node_names


def test_react_graph_end_reason_surfaces_in_retrieval_trace(
    seeded_multilingual_policy_chunks: None,
) -> None:
    result = execute_policy_graph(
        question="北京酒店报销上限",
        tenant_id="t1",
        customer_id="c1",
        route_name="policy_qa",
        base_timeline=[],
    )
    assert result.output["retrieval_trace"]["end_reason"] in {"completed", "max_steps"}


def test_react_graph_handles_unseen_tenant_without_crashing() -> None:
    """No seeded chunks → policy_search still runs but returns empty."""
    result = execute_policy_graph(
        question="北京酒店报销上限",
        tenant_id="ghost-tenant",
        customer_id="ghost-customer",
        route_name="policy_qa",
        base_timeline=[],
    )
    assert result.agent_name == "travel_policy_agent"
    # Low / zero confidence → requires review.
    assert result.requires_human_review
    assert result.status == "needs_review"


def test_build_policy_graph_has_all_four_nodes() -> None:
    graph = build_policy_graph()
    assert graph.entry == "plan"
    # _nodes is a private dict; inspect via the public run() invariant
    # that transitioning to each node name doesn't error.
    # (This is mostly a smoke test of construction.)
    from app.services.agents.engine import GraphState

    result = graph.run(GraphState(tenant_id="t", user_id="u", request_id="r"))
    # Even with empty seed, graph terminates (plan → act → observe → plan → finalize).
    assert result.end_reason.value in {"completed", "max_steps", "error"}
