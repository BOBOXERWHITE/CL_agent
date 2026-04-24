"""Minimal state machine engine for agent graphs (P3.1).

Why hand-roll instead of LangGraph:

- The only three agents in this codebase (policy / ticket_router / anomaly)
  do not need multi-agent coordination or distributed state.
- LangGraph pulls a heavy transitive stack (langchain-core, pydantic v1/v2
  adapters, etc.); we already use pydantic v2 natively and a single extra
  dependency would be a non-trivial upgrade surface.
- 100 lines of deliberate engine gives us exact control over event
  emission, state immutability semantics, and integration with Phase 0's
  audit / lifespan / RLS scoping.

Usage (subsequent sub-tasks migrate to this API):

    graph = Graph(
        nodes={"plan": plan_node, "exec": exec_node, "finalize": final_node},
        entry="plan",
    )
    result = graph.run(GraphState(tenant_id="t", user_id="u", request_id="r"))
    # result.state has the terminal GraphState, result.events is the full
    # ordered list of TimelineEvents, result.error is set iff a node raised.

Each node is a pure function of ``GraphState`` that returns a
``NodeResult``. State mutation is explicit via ``state_delta``; nodes
MUST NOT mutate the state argument itself. This keeps the engine's event
timeline consistent with what actually changed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Event vocabulary
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Structured event vocabulary (P3.7 maps these to the audit table).

    Enum string values are the wire format -- keep them stable. New event
    kinds go at the end; do not rename existing values.
    """

    NODE_START = "NODE_START"
    NODE_END = "NODE_END"
    NODE_ERROR = "NODE_ERROR"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_END = "TOOL_CALL_END"
    LLM_CALL = "LLM_CALL"
    MEMORY_WRITE = "MEMORY_WRITE"
    MEMORY_READ = "MEMORY_READ"
    ROUTE_DECISION = "ROUTE_DECISION"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    GRAPH_END = "GRAPH_END"
    GRAPH_MAX_STEPS = "GRAPH_MAX_STEPS"


@dataclass(frozen=True)
class TimelineEvent:
    """One structured event on the agent timeline.

    P3.7 persists these to the ``agent_event`` table; meanwhile the engine
    returns them in-memory on the ``GraphRunResult``.
    """

    sequence: int
    event_type: EventType
    node_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "node_name": self.node_name,
            "payload": dict(self.payload),
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class GraphState:
    """Mutable shared state passed through every node.

    Field design:
    - ``tenant_id`` / ``user_id`` / ``request_id`` come from the FastAPI
      RequestContext; they're in the state so nodes can pass them to
      downstream services (cache keys, RLS scoping, audit rows) without
      re-reading ``contextvars``.
    - ``messages`` holds the ChatMessage-like record accumulated as the
      graph runs; downstream P3.6 memory uses this for short-term recall.
    - ``scratchpad`` is an open bag for node-to-node communication (e.g.
      plan node writes ``plan``, exec reads it, observe writes
      ``observation``, reflect reads both). Keys are by convention.
    - ``tool_calls`` captures every ``ToolCallRecord`` produced; bridges
      into the existing ``AgentRun`` persistence unchanged.
    - ``paused_reason`` is populated by a node when it needs HITL (P3.8).
    """

    tenant_id: str = ""
    user_id: str = ""
    request_id: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    scratchpad: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory: list[dict[str, Any]] = field(default_factory=list)
    paused_reason: str | None = None

    def clone(self) -> GraphState:
        """Return a deep-ish copy suitable for snapshotting."""
        return GraphState(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            request_id=self.request_id,
            messages=list(self.messages),
            scratchpad=dict(self.scratchpad),
            tool_calls=list(self.tool_calls),
            memory=list(self.memory),
            paused_reason=self.paused_reason,
        )


@dataclass(frozen=True)
class NodeResult:
    """What a node returns to the engine.

    - ``next_node=None`` terminates the graph (successful completion).
    - ``next_node=<name>`` transitions to that node on the next iteration.
    - ``state_delta`` is merged into ``GraphState`` using "last write wins"
      for top-level fields; for dict fields (scratchpad) the delta is
      deep-merged. Lists (messages / tool_calls / memory) are *appended*.
    - ``events`` are engine-visible markers; the engine also auto-emits
      NODE_START / NODE_END around each call.
    - ``pause`` = True signals HITL intent; equivalent to setting
      ``state_delta["paused_reason"] = "..."``.
    """

    next_node: str | None
    state_delta: dict[str, Any] = field(default_factory=dict)
    events: list[TimelineEvent] = field(default_factory=list)


# Node signature: given state, return a result.
# Engine passes the state BY VALUE (cloned) so nodes can't accidentally
# mutate it; any changes must go through ``state_delta``.
NodeFn = Callable[[GraphState], NodeResult]


# ---------------------------------------------------------------------------
# Run results
# ---------------------------------------------------------------------------


class GraphEndReason(str, Enum):
    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    PAUSED = "paused"
    ERROR = "error"


@dataclass(frozen=True)
class GraphRunResult:
    """What ``Graph.run`` returns.

    - ``state`` is the final ``GraphState`` after all transitions.
    - ``events`` is the ordered timeline (engine events + node events).
    - ``end_reason`` says why the loop stopped; ``error`` is populated
      iff ``end_reason == ERROR``.
    - ``steps`` is the count of node executions (useful for quota / cost).
    """

    state: GraphState
    events: list[TimelineEvent]
    end_reason: GraphEndReason
    steps: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class GraphConfigError(ValueError):
    """Raised for static errors in a Graph definition (bad entry, unknown node)."""


class Graph:
    """Minimal state machine. Not thread-safe; construct one per request."""

    def __init__(
        self,
        *,
        nodes: dict[str, NodeFn],
        entry: str,
    ) -> None:
        if not nodes:
            raise GraphConfigError("graph requires at least one node")
        if entry not in nodes:
            raise GraphConfigError(f"entry node {entry!r} not registered")
        self._nodes = dict(nodes)
        self._entry = entry

    @property
    def entry(self) -> str:
        return self._entry

    def run(
        self,
        initial_state: GraphState,
        *,
        max_steps: int = 10,
    ) -> GraphRunResult:
        """Execute the graph from ``entry`` until a terminal condition.

        Terminal conditions (in priority order):
        1. A node returns ``next_node=None`` → COMPLETED
        2. ``paused_reason`` gets set on the state → PAUSED (HITL)
        3. Step count hits ``max_steps`` → MAX_STEPS (safety)
        4. A node raises → ERROR (engine swallows exception, marks state)
        """
        state = initial_state.clone()
        events: list[TimelineEvent] = []
        sequence = 0
        current_node: str | None = self._entry
        steps = 0

        while current_node is not None:
            if steps >= max_steps:
                events.append(
                    TimelineEvent(
                        sequence=sequence,
                        event_type=EventType.GRAPH_MAX_STEPS,
                        node_name=current_node,
                        payload={"max_steps": max_steps, "steps": steps},
                    )
                )
                return GraphRunResult(
                    state=state,
                    events=events,
                    end_reason=GraphEndReason.MAX_STEPS,
                    steps=steps,
                )

            if current_node not in self._nodes:
                error_msg = f"graph transitioned to unknown node {current_node!r}"
                events.append(
                    TimelineEvent(
                        sequence=sequence,
                        event_type=EventType.NODE_ERROR,
                        node_name=current_node,
                        payload={"error": error_msg},
                    )
                )
                return GraphRunResult(
                    state=state,
                    events=events,
                    end_reason=GraphEndReason.ERROR,
                    steps=steps,
                    error=error_msg,
                )

            node_fn = self._nodes[current_node]

            # NODE_START
            events.append(
                TimelineEvent(
                    sequence=sequence,
                    event_type=EventType.NODE_START,
                    node_name=current_node,
                )
            )
            sequence += 1

            try:
                result = node_fn(state.clone())
                # Apply state delta inside the try: malformed deltas
                # (unknown keys, wrong types) are authoring bugs we surface
                # as graph errors rather than letting them crash the
                # caller. The delta's list-append rules are easy to
                # get wrong; failing loudly to the run result is kinder.
                new_state = _apply_delta(state, result.state_delta)
            except Exception as exc:
                error_msg = str(exc)
                events.append(
                    TimelineEvent(
                        sequence=sequence,
                        event_type=EventType.NODE_ERROR,
                        node_name=current_node,
                        payload={
                            "error": error_msg,
                            "exception_type": type(exc).__name__,
                        },
                    )
                )
                return GraphRunResult(
                    state=state,
                    events=events,
                    end_reason=GraphEndReason.ERROR,
                    steps=steps + 1,
                    error=error_msg,
                )

            # Merge node-emitted events with sequence numbers reassigned.
            for node_event in result.events:
                events.append(
                    TimelineEvent(
                        sequence=sequence,
                        event_type=node_event.event_type,
                        node_name=node_event.node_name or current_node,
                        payload=node_event.payload,
                        timestamp=node_event.timestamp,
                    )
                )
                sequence += 1

            state = new_state
            steps += 1

            # NODE_END — record next_node for traceability.
            events.append(
                TimelineEvent(
                    sequence=sequence,
                    event_type=EventType.NODE_END,
                    node_name=current_node,
                    payload={"next_node": result.next_node},
                )
            )
            sequence += 1

            # HITL: a node populated paused_reason → stop the loop.
            if state.paused_reason is not None:
                events.append(
                    TimelineEvent(
                        sequence=sequence,
                        event_type=EventType.PAUSE,
                        node_name=current_node,
                        payload={"reason": state.paused_reason},
                    )
                )
                return GraphRunResult(
                    state=state,
                    events=events,
                    end_reason=GraphEndReason.PAUSED,
                    steps=steps,
                )

            current_node = result.next_node

        # Normal completion.
        events.append(
            TimelineEvent(
                sequence=sequence,
                event_type=EventType.GRAPH_END,
                node_name="",
                payload={"steps": steps},
            )
        )
        return GraphRunResult(
            state=state,
            events=events,
            end_reason=GraphEndReason.COMPLETED,
            steps=steps,
        )


# ---------------------------------------------------------------------------
# State delta merge
# ---------------------------------------------------------------------------


_LIST_APPEND_FIELDS: frozenset[str] = frozenset({"messages", "tool_calls", "memory"})


def _apply_delta(state: GraphState, delta: dict[str, Any]) -> GraphState:
    """Return a new GraphState with ``delta`` applied.

    Rules:
    - ``tenant_id`` / ``user_id`` / ``request_id`` / ``paused_reason``:
      last-write-wins (plain assignment).
    - ``messages`` / ``tool_calls`` / ``memory``: delta values are
      *appended* to the existing list. This matches the natural semantics
      (nodes contribute records, they don't rewrite history).
    - ``scratchpad``: shallow-merged (delta keys overwrite).
    - Unknown keys raise -- we want a typo in ``state_delta`` to surface
      immediately, not silently be dropped.
    """
    if not delta:
        return state

    new = state.clone()

    for key, value in delta.items():
        if key in {"tenant_id", "user_id", "request_id", "paused_reason"}:
            setattr(new, key, value)
        elif key == "scratchpad":
            if not isinstance(value, dict):
                raise TypeError("scratchpad delta must be a dict")
            new.scratchpad = {**new.scratchpad, **value}
        elif key in _LIST_APPEND_FIELDS:
            if not isinstance(value, list):
                raise TypeError(f"{key} delta must be a list")
            getattr(new, key).extend(value)
        else:
            raise KeyError(
                f"unknown state_delta key {key!r}; valid keys are "
                f"tenant_id / user_id / request_id / paused_reason / "
                f"scratchpad / messages / tool_calls / memory"
            )

    return new


__all__ = [
    "EventType",
    "Graph",
    "GraphConfigError",
    "GraphEndReason",
    "GraphRunResult",
    "GraphState",
    "NodeFn",
    "NodeResult",
    "TimelineEvent",
]
