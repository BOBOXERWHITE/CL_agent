"""Policy-QA agent graph, rewritten to use the P3.1 engine.

Shape
-----

Minimal ReAct scaffold:

    plan ──▶ act ──▶ observe ──▶ plan ──▶ ... ──▶ finalize

- ``plan``   picks the next action. With a deterministic LLM (tests) the
              plan is hard-coded: "if no observation yet, call
              policy_search; otherwise finalize". With a real LLM this
              node is the natural extension point to let the model
              choose between tools / decide when it has enough
              evidence. The scaffold is identical either way.
- ``act``    runs the chosen tool through ``tool_runner``, which handles
              retries, circuit breaking, and event emission for free.
- ``observe`` folds the tool output into ``scratchpad.observations`` so
              ``plan`` sees it on the next tick.
- ``finalize`` synthesises the final answer from the accumulated
               observations and returns to the caller.

The existing ``execute_policy_graph`` signature is preserved so the
legacy ``graph.py`` dispatcher doesn't need changes. Internally it now
routes through ``Graph.run``; the timeline + tool_calls captured by the
engine are translated back into the pre-Phase-3 ``AgentExecutionResult``
shape the API contract expects.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.services.agents.engine import (
    EventType,
    Graph,
    GraphEndReason,
    GraphRunResult,
    GraphState,
    NodeResult,
    TimelineEvent,
)
from app.services.agents.nodes import append_timeline_step
from app.services.agents.state import AgentExecutionResult, TimelineStep, ToolCallRecord
from app.services.agents.tool_runner import (
    ToolInvocationStatus,
    ToolRunner,
    get_default_tool_runner,
)

MAX_REACT_STEPS = 8  # one ReAct loop = plan+act+observe+plan+finalize (5);
#                     allow headroom for up to 2 tool-call cycles.


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _plan_node(state: GraphState) -> NodeResult:
    """Decide whether to call a tool or finalize.

    Deterministic policy: if we haven't yet observed any retrieval
    result, call ``policy_search``. Once we have an observation, move on
    to finalize. That's one ReAct cycle -- enough to prove the scaffold
    works end-to-end while keeping tests deterministic without a real
    LLM.
    """
    observations = state.scratchpad.get("observations", [])
    if not observations:
        plan = {"action": "call_tool", "tool": "policy_search"}
        return NodeResult(
            next_node="act",
            state_delta={"scratchpad": {"plan": plan}},
        )
    return NodeResult(
        next_node="finalize",
        state_delta={"scratchpad": {"plan": {"action": "finalize"}}},
    )


def _act_node(state: GraphState) -> NodeResult:
    """Run the tool picked by ``plan``.

    Uses the default ToolRunner so retries + circuit breaker apply.
    Failures do not raise -- the observation just records the failure
    status, and ``plan`` / ``finalize`` decide how to react.
    """
    plan = state.scratchpad.get("plan") or {}
    tool_name = plan.get("tool")
    if plan.get("action") != "call_tool" or not tool_name:
        # Nothing to do -- shouldn't happen with this deterministic plan,
        # but stay defensive.
        return NodeResult(next_node="finalize")

    runner: ToolRunner = get_default_tool_runner()
    raw_input: dict[str, Any] = {
        "question": state.scratchpad.get("question", ""),
        "tenant_id": state.tenant_id,
        "customer_id": state.scratchpad.get("customer_id", ""),
    }
    result = runner.run(tool_name, raw_input)

    tool_call_record = {
        "tool_name": tool_name,
        "status": result.status.value,
        "latency_ms": result.latency_ms,
        "input_payload": result.input_payload,
        "output_payload": result.output_payload,
    }
    state_delta: dict[str, Any] = {
        "scratchpad": {"last_tool_status": result.status.value},
        "tool_calls": [tool_call_record],
    }
    return NodeResult(
        next_node="observe",
        state_delta=state_delta,
        events=list(result.events),
    )


def _observe_node(state: GraphState) -> NodeResult:
    """Fold the last tool output into the observations list."""
    tool_calls = state.tool_calls
    if not tool_calls:
        return NodeResult(next_node="plan")
    last = tool_calls[-1]
    observation = {
        "tool": last["tool_name"],
        "status": last["status"],
        "output": last["output_payload"],
    }
    return NodeResult(
        next_node="plan",
        state_delta={
            "scratchpad": {"observations": [*state.scratchpad.get("observations", []), observation]}
        },
    )


def _finalize_node(state: GraphState) -> NodeResult:
    """Synthesise the final answer from the first successful observation.

    Because we only call one tool (``policy_search``) and it returns a
    complete ``PolicySearchOutput`` dict, "synthesis" is just picking
    that dict out and copying the fields into a fixed result shape.
    Later versions where ``plan`` orchestrates multiple tools will
    aggregate here instead.
    """
    observations = state.scratchpad.get("observations", [])
    last_status = state.scratchpad.get("last_tool_status")
    if not observations or last_status != ToolInvocationStatus.COMPLETED.value:
        final = {
            "answer": (
                "当前没有检索到足够的政策证据，暂时无法给出可信回答。"
                if state.scratchpad.get("is_chinese", False)
                else "I do not have enough policy evidence to answer this question confidently yet."
            ),
            "confidence": 0.0,
            "citations": [],
            "retrieval_mode": state.scratchpad.get("last_tool_status", "unavailable"),
            "prompt_template_id": None,
        }
    else:
        output = observations[-1]["output"] or {}
        final = {
            "answer": output.get("answer", ""),
            "confidence": float(output.get("confidence", 0.0)),
            "citations": output.get("citations", []),
            "retrieval_mode": output.get("retrieval_mode", "unknown"),
            "prompt_template_id": output.get("prompt_template_id"),
        }

    return NodeResult(
        next_node=None,
        state_delta={"scratchpad": {"final": final}},
    )


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_policy_graph() -> Graph:
    """Exposed for tests that want to run the graph without the full
    ``execute_policy_graph`` adapter.
    """
    return Graph(
        nodes={
            "plan": _plan_node,
            "act": _act_node,
            "observe": _observe_node,
            "finalize": _finalize_node,
        },
        entry="plan",
    )


# ---------------------------------------------------------------------------
# Bridge from engine run result → legacy AgentExecutionResult
# ---------------------------------------------------------------------------


def _events_to_timeline_steps(
    events: list[TimelineEvent],
    *,
    base: list[TimelineStep],
) -> list[TimelineStep]:
    """Flatten engine events into the legacy TimelineStep list.

    Keeps only the "meaningful" events (NODE_START / PAUSE / END) so the
    operator-facing timeline doesn't explode. All events still live on
    ``AgentRun.timeline_json`` when P3.7 lands; this is the display view.
    """
    steps = list(base)
    for event in events:
        if event.event_type == EventType.NODE_START:
            append_timeline_step(
                steps,
                node_name=event.node_name,
                status="started",
                detail=f"节点 {event.node_name} 开始执行。",
            )
        elif event.event_type == EventType.TOOL_CALL_END:
            payload = event.payload or {}
            status = payload.get("status", "")
            tool = payload.get("tool", "")
            append_timeline_step(
                steps,
                node_name="tool_call",
                status=status,
                detail=f"工具 {tool} 调用 {status}。",
            )
        elif event.event_type == EventType.PAUSE:
            append_timeline_step(
                steps,
                node_name="human_review_checkpoint",
                status="required",
                detail=str((event.payload or {}).get("reason", "需要人工复核")),
            )
    return steps


def _collect_tool_call_records(state: GraphState) -> list[ToolCallRecord]:
    """Convert ``state.tool_calls`` (list[dict]) to typed ``ToolCallRecord``s."""
    return [
        ToolCallRecord(
            tool_name=entry.get("tool_name", ""),
            status=entry.get("status", ""),
            latency_ms=int(entry.get("latency_ms", 0)),
            input_payload=entry.get("input_payload", {}) or {},
            output_payload=entry.get("output_payload", {}) or {},
        )
        for entry in state.tool_calls
    ]


def _run_result_to_execution(
    run_result: GraphRunResult,
    *,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    """Translate engine output back to the legacy contract."""
    final = run_result.state.scratchpad.get("final") or {
        "answer": "",
        "confidence": 0.0,
        "citations": [],
    }
    confidence = float(final.get("confidence", 0.0))
    settings = get_settings()
    requires_human_review = (
        run_result.end_reason == GraphEndReason.PAUSED
        or confidence < settings.chat_confidence_threshold
    )
    if run_result.end_reason == GraphEndReason.ERROR:
        status = "failed"
    elif run_result.end_reason == GraphEndReason.PAUSED or requires_human_review:
        status = "needs_review"
    else:
        status = "completed"

    timeline = _events_to_timeline_steps(run_result.events, base=base_timeline)
    tool_calls = _collect_tool_call_records(run_result.state)

    return AgentExecutionResult(
        agent_name="travel_policy_agent",
        route_name=route_name,
        status=status,
        confidence=confidence,
        requires_human_review=requires_human_review,
        output={
            "answer": final.get("answer", ""),
            "citations": final.get("citations", []),
            "retrieval_trace": {
                "mode": final.get("retrieval_mode", "unknown"),
                "prompt_template_id": final.get("prompt_template_id"),
                "react_steps": run_result.steps,
                "end_reason": run_result.end_reason.value,
            },
        },
        timeline=timeline,
        tool_calls=tool_calls,
        # P3.7: hand the structured engine events to the route so they get
        # flushed to ``agent_event`` in the same transaction as AgentRun.
        engine_events=list(run_result.events),
    )


# ---------------------------------------------------------------------------
# Public entry (legacy signature, new internals)
# ---------------------------------------------------------------------------


def execute_policy_graph(
    *,
    question: str,
    tenant_id: str,
    customer_id: str,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    from app.services.rag.text_processing import extract_cjk_sequences

    initial_state = GraphState(
        tenant_id=tenant_id,
        user_id="",  # not threaded through the existing entrypoint yet
        request_id="",
        scratchpad={
            "question": question,
            "customer_id": customer_id,
            "is_chinese": bool(extract_cjk_sequences(question)),
        },
    )
    graph = build_policy_graph()
    run_result = graph.run(initial_state, max_steps=MAX_REACT_STEPS)
    return _run_result_to_execution(
        run_result,
        route_name=route_name,
        base_timeline=base_timeline,
    )
