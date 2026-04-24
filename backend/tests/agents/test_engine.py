"""Tests for the P3.1 agent engine.

Covers the engine's **behavioural contract**: state immutability,
transition semantics, delta merge rules, max_steps safety, pause (HITL),
and error containment. These tests do NOT exercise real agent logic --
that comes in P3.2+ via nodes that use this engine.
"""

from __future__ import annotations

import pytest

from app.services.agents.engine import (
    EventType,
    Graph,
    GraphConfigError,
    GraphEndReason,
    GraphState,
    NodeResult,
    TimelineEvent,
)

# --- helpers ----------------------------------------------------------------


def _record_only_node(name: str, next_node: str | None):
    """A node that just records its own name in the scratchpad and moves on."""

    def node(state: GraphState) -> NodeResult:
        visited = list(state.scratchpad.get("visited", []))
        visited.append(name)
        return NodeResult(next_node=next_node, state_delta={"scratchpad": {"visited": visited}})

    return node


def _base_state() -> GraphState:
    return GraphState(tenant_id="t1", user_id="u1", request_id="r1")


# --- construction -----------------------------------------------------------


def test_graph_rejects_empty_nodes() -> None:
    with pytest.raises(GraphConfigError):
        Graph(nodes={}, entry="x")


def test_graph_rejects_unknown_entry() -> None:
    with pytest.raises(GraphConfigError):
        Graph(nodes={"a": _record_only_node("a", None)}, entry="b")


# --- basic transitions ------------------------------------------------------


def test_single_node_graph_completes() -> None:
    graph = Graph(nodes={"only": _record_only_node("only", None)}, entry="only")
    result = graph.run(_base_state())
    assert result.end_reason == GraphEndReason.COMPLETED
    assert result.steps == 1
    assert result.state.scratchpad["visited"] == ["only"]


def test_multi_node_graph_follows_transitions() -> None:
    graph = Graph(
        nodes={
            "a": _record_only_node("a", "b"),
            "b": _record_only_node("b", "c"),
            "c": _record_only_node("c", None),
        },
        entry="a",
    )
    result = graph.run(_base_state())
    assert result.end_reason == GraphEndReason.COMPLETED
    assert result.state.scratchpad["visited"] == ["a", "b", "c"]
    assert result.steps == 3


def test_graph_auto_emits_node_start_and_end_events() -> None:
    graph = Graph(nodes={"only": _record_only_node("only", None)}, entry="only")
    result = graph.run(_base_state())
    event_types = [e.event_type for e in result.events]
    assert EventType.NODE_START in event_types
    assert EventType.NODE_END in event_types
    assert EventType.GRAPH_END in event_types


def test_graph_preserves_event_sequence_numbers_monotonic() -> None:
    graph = Graph(
        nodes={
            "a": _record_only_node("a", "b"),
            "b": _record_only_node("b", None),
        },
        entry="a",
    )
    result = graph.run(_base_state())
    sequences = [e.sequence for e in result.events]
    assert sequences == sorted(sequences)


# --- state delta merge ------------------------------------------------------


def test_list_fields_are_appended_not_overwritten() -> None:
    """messages / tool_calls / memory deltas must extend, not replace."""

    def append_msg(label: str):
        def node(_state: GraphState) -> NodeResult:
            return NodeResult(
                next_node=None if label == "b" else "b",
                state_delta={"messages": [{"role": "system", "content": label}]},
            )

        return node

    graph = Graph(nodes={"a": append_msg("a"), "b": append_msg("b")}, entry="a")
    result = graph.run(_base_state())
    assert [m["content"] for m in result.state.messages] == ["a", "b"]


def test_scratchpad_deltas_merge_shallowly() -> None:
    def write_k1(_: GraphState) -> NodeResult:
        return NodeResult(next_node="b", state_delta={"scratchpad": {"k1": "v1"}})

    def write_k2(_: GraphState) -> NodeResult:
        return NodeResult(next_node=None, state_delta={"scratchpad": {"k2": "v2"}})

    graph = Graph(nodes={"a": write_k1, "b": write_k2}, entry="a")
    result = graph.run(_base_state())
    assert result.state.scratchpad == {"k1": "v1", "k2": "v2"}


def test_scratchpad_later_write_overwrites_same_key() -> None:
    def write1(_: GraphState) -> NodeResult:
        return NodeResult(next_node="b", state_delta={"scratchpad": {"k": "first"}})

    def write2(_: GraphState) -> NodeResult:
        return NodeResult(next_node=None, state_delta={"scratchpad": {"k": "second"}})

    graph = Graph(nodes={"a": write1, "b": write2}, entry="a")
    result = graph.run(_base_state())
    assert result.state.scratchpad == {"k": "second"}


def test_unknown_delta_key_raises() -> None:
    def bad_node(_: GraphState) -> NodeResult:
        return NodeResult(next_node=None, state_delta={"bogus": "x"})

    graph = Graph(nodes={"a": bad_node}, entry="a")
    result = graph.run(_base_state())
    assert result.end_reason == GraphEndReason.ERROR
    assert result.error is not None and "bogus" in result.error


def test_scratchpad_delta_must_be_dict() -> None:
    def bad_node(_: GraphState) -> NodeResult:
        return NodeResult(next_node=None, state_delta={"scratchpad": "not a dict"})

    result = Graph(nodes={"a": bad_node}, entry="a").run(_base_state())
    assert result.end_reason == GraphEndReason.ERROR


# --- state immutability -----------------------------------------------------


def test_node_sees_clone_cannot_mutate_engine_state() -> None:
    """A node mutating the state arg in place must NOT affect the engine."""

    def mutating_node(state: GraphState) -> NodeResult:
        state.scratchpad["leaked"] = "should not appear"
        return NodeResult(next_node=None, state_delta={})

    graph = Graph(nodes={"only": mutating_node}, entry="only")
    result = graph.run(_base_state())
    assert "leaked" not in result.state.scratchpad


# --- max steps safety -------------------------------------------------------


def test_infinite_loop_terminated_by_max_steps() -> None:
    """A → B → A → B ... caught by max_steps guard."""

    def to_b(_: GraphState) -> NodeResult:
        return NodeResult(next_node="b")

    def to_a(_: GraphState) -> NodeResult:
        return NodeResult(next_node="a")

    graph = Graph(nodes={"a": to_b, "b": to_a}, entry="a")
    result = graph.run(_base_state(), max_steps=4)
    assert result.end_reason == GraphEndReason.MAX_STEPS
    assert result.steps == 4


# --- error containment ------------------------------------------------------


def test_node_exception_marks_result_error_without_propagating() -> None:
    def boom(_: GraphState) -> NodeResult:
        raise RuntimeError("kaboom")

    result = Graph(nodes={"a": boom}, entry="a").run(_base_state())
    assert result.end_reason == GraphEndReason.ERROR
    assert result.error == "kaboom"
    # An error event must be recorded with the exception type.
    error_events = [e for e in result.events if e.event_type == EventType.NODE_ERROR]
    assert len(error_events) == 1
    assert error_events[0].payload["exception_type"] == "RuntimeError"


def test_transition_to_unknown_node_errors_cleanly() -> None:
    def bad_transition(_: GraphState) -> NodeResult:
        return NodeResult(next_node="nonexistent")

    result = Graph(nodes={"a": bad_transition}, entry="a").run(_base_state())
    assert result.end_reason == GraphEndReason.ERROR
    assert result.error is not None and "nonexistent" in result.error


# --- pause (HITL) -----------------------------------------------------------


def test_node_setting_paused_reason_stops_the_graph() -> None:
    def pause_here(_: GraphState) -> NodeResult:
        return NodeResult(
            next_node="b",  # would continue if not for the pause
            state_delta={"paused_reason": "needs approval"},
        )

    def should_not_run(_: GraphState) -> NodeResult:  # pragma: no cover
        raise AssertionError("graph did not pause")

    graph = Graph(nodes={"a": pause_here, "b": should_not_run}, entry="a")
    result = graph.run(_base_state())
    assert result.end_reason == GraphEndReason.PAUSED
    assert result.state.paused_reason == "needs approval"
    pause_events = [e for e in result.events if e.event_type == EventType.PAUSE]
    assert len(pause_events) == 1


# --- node-emitted events ---------------------------------------------------


def test_node_events_are_interleaved_with_engine_events() -> None:
    def node_with_custom_event(_: GraphState) -> NodeResult:
        return NodeResult(
            next_node=None,
            events=[
                TimelineEvent(
                    sequence=999,  # engine reassigns this; verify it does.
                    event_type=EventType.LLM_CALL,
                    node_name="only",
                    payload={"model": "test"},
                )
            ],
        )

    graph = Graph(nodes={"only": node_with_custom_event}, entry="only")
    result = graph.run(_base_state())
    llm_events = [e for e in result.events if e.event_type == EventType.LLM_CALL]
    assert len(llm_events) == 1
    # Engine reassigns sequence so all events are monotonic; the 999
    # sentinel must be gone.
    assert llm_events[0].sequence != 999
    # Node event appears between NODE_START and NODE_END of "only".
    seq_by_type = {e.event_type: e.sequence for e in result.events}
    assert seq_by_type[EventType.NODE_START] < llm_events[0].sequence
    assert seq_by_type[EventType.NODE_END] > llm_events[0].sequence


def test_event_as_dict_roundtrips_all_fields() -> None:
    event = TimelineEvent(
        sequence=1,
        event_type=EventType.TOOL_CALL_START,
        node_name="exec",
        payload={"tool": "policy_search"},
    )
    d = event.as_dict()
    assert d["sequence"] == 1
    assert d["event_type"] == "TOOL_CALL_START"
    assert d["node_name"] == "exec"
    assert d["payload"] == {"tool": "policy_search"}
    assert "timestamp" in d
