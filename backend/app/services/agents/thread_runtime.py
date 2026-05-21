from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models.agent import AgentThread, AgentThreadCheckpoint
from app.db.models.agent_event import AgentEvent
from app.db.models.rule import ReviewCase
from app.services.agents.state import AgentExecutionResult, TimelineStep, ToolCallRecord


def _serialize_timeline(steps: list[TimelineStep]) -> list[dict[str, object]]:
    return [step.as_dict() for step in steps]


def _serialize_tool_calls(tool_calls: list[ToolCallRecord]) -> list[dict[str, object]]:
    return [call.as_dict() for call in tool_calls]


def _serialize_timeline_nodes_from_result(result: AgentExecutionResult) -> list[dict[str, Any]]:
    return [
        {
            "node_name": step.node_name,
            "status": step.status,
            "detail": step.detail,
            "timestamp": step.timestamp.isoformat(),
        }
        for step in result.timeline
    ]


def _serialize_timeline_nodes_from_payload(
    timeline_nodes: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for node in timeline_nodes or []:
        timestamp = node.get("timestamp")
        if isinstance(timestamp, datetime):
            timestamp_value = timestamp.isoformat()
        elif isinstance(timestamp, str):
            timestamp_value = timestamp
        else:
            timestamp_value = None
        serialized.append(
            {
                "node_name": str(node.get("node_name", "")),
                "status": str(node.get("status", "")),
                "detail": str(node.get("detail", "")),
                "timestamp": timestamp_value,
            }
        )
    return serialized


def _serialize_tool_calls_from_result(result: AgentExecutionResult) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": call.tool_name,
            "status": call.status,
            "latency_ms": call.latency_ms,
        }
        for call in result.tool_calls
    ]


def _serialize_tool_calls_from_payload(
    tool_calls: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for call in tool_calls or []:
        latency_ms = call.get("latency_ms")
        serialized.append(
            {
                "tool_name": str(call.get("tool_name", "")),
                "status": str(call.get("status", "")),
                "latency_ms": int(latency_ms) if isinstance(latency_ms, int | float) else None,
            }
        )
    return serialized


def _event_timestamp(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    return datetime.now(UTC).isoformat()


def serialize_checkpoint_summary(
    checkpoint: AgentThreadCheckpoint | None,
) -> dict[str, object] | None:
    if checkpoint is None:
        return None
    return {
        "id": checkpoint.id,
        "checkpoint_type": checkpoint.checkpoint_type,
        "status": checkpoint.status,
        "created_at": checkpoint.created_at.isoformat(),
    }


def build_checkpoint_state(
    result: AgentExecutionResult,
    *,
    output_override: dict[str, object] | None = None,
) -> dict[str, object]:
    state_json: dict[str, object] = dict(result.checkpoint_payload or {})
    state_json.setdefault("agent_name", result.agent_name)
    state_json.setdefault("route_name", result.route_name)
    state_json.setdefault("status", result.status)
    state_json.setdefault("confidence", result.confidence)
    state_json.setdefault("requires_human_review", result.requires_human_review)
    state_json.setdefault("output", dict(output_override or result.output))
    state_json.setdefault("timeline", _serialize_timeline(result.timeline))
    state_json.setdefault("tool_calls", _serialize_tool_calls(result.tool_calls))
    state_json.setdefault(
        "engine_events",
        [event.as_dict() for event in result.engine_events],
    )
    if result.interrupt is not None:
        state_json.setdefault("interrupt", dict(result.interrupt))
    return state_json


def _normalize_event_row(event: AgentEvent) -> dict[str, Any]:
    payload = dict(event.payload_json or {})
    event_type = str(event.event_type or "").upper()
    category = "engine"
    name = event_type.lower() if event_type else "event"
    status = "info"
    detail = str(payload.get("detail") or payload.get("reason") or event.node_name or name)

    if event_type == "ROUTE_DECISION":
        category = "router"
        name = "route_decision"
        status = "completed"
        detail = str(
            payload.get("route_name") or payload.get("target") or payload.get("decision") or detail
        )
    elif event_type in {"NODE_START", "NODE_END", "NODE_ERROR", "GRAPH_END", "GRAPH_MAX_STEPS"}:
        category = "engine"
        name = event_type.lower()
        status = (
            "started"
            if event_type == "NODE_START"
            else "error"
            if event_type == "NODE_ERROR"
            else "blocked"
            if event_type == "GRAPH_MAX_STEPS"
            else "completed"
        )
        detail = str(payload.get("error") or event.node_name or name)
    elif event_type in {"TOOL_CALL_START", "TOOL_CALL_END"}:
        category = "tool"
        name = event_type.lower()
        status = "started" if event_type == "TOOL_CALL_START" else "completed"
        detail = str(payload.get("tool_name") or event.node_name or name)
    elif event_type == "LLM_CALL":
        category = "specialist"
        name = "llm_call"
        status = "completed"
        detail = str(payload.get("model_name") or event.node_name or name)
    elif event_type in {"MEMORY_READ", "MEMORY_WRITE"}:
        category = "memory"
        name = event_type.lower()
        status = "completed"
        detail = str(payload.get("key") or payload.get("memory_key") or event.node_name or name)
    elif event_type == "PAUSE":
        category = "interrupt"
        name = "pause"
        status = "paused"
        detail = str(payload.get("reason") or detail)
    elif event_type == "RESUME":
        category = "review"
        name = "resume"
        decision = str(payload.get("decision") or "").strip()
        status = "rejected" if decision == "reject" else "completed"
        detail = decision or str(payload.get("note") or "resume")

    return {
        "category": category,
        "name": name,
        "status": status,
        "detail": detail,
        "timestamp": _event_timestamp(event.created_at),
        "metadata": payload,
    }


def build_trace_events(
    *,
    agent_events: Sequence[AgentEvent] | None = None,
    checkpoint: AgentThreadCheckpoint | None = None,
    pending_interrupt: dict[str, Any] | None = None,
    review_case: ReviewCase | None = None,
) -> list[dict[str, Any]]:
    trace_events = [_normalize_event_row(event) for event in agent_events or []]

    if checkpoint is not None:
        trace_events.append(
            {
                "category": "checkpoint",
                "name": "checkpoint_state",
                "status": checkpoint.status,
                "detail": checkpoint.checkpoint_type,
                "timestamp": checkpoint.created_at.isoformat(),
                "metadata": {
                    "checkpoint_id": checkpoint.id,
                    "checkpoint_type": checkpoint.checkpoint_type,
                    "status": checkpoint.status,
                },
            }
        )

    interrupt = dict(pending_interrupt or {})
    if interrupt:
        trace_events.append(
            {
                "category": "interrupt",
                "name": str(interrupt.get("kind") or "interrupt"),
                "status": "paused",
                "detail": str(
                    interrupt.get("reason") or interrupt.get("queue_name") or "interrupt pending"
                ),
                "timestamp": checkpoint.created_at.isoformat()
                if checkpoint is not None
                else datetime.now(UTC).isoformat(),
                "metadata": interrupt,
            }
        )

    if review_case is not None:
        trace_events.append(
            {
                "category": "review",
                "name": "review_case",
                "status": review_case.status,
                "detail": review_case.reason or "review case is waiting in queue",
                "timestamp": review_case.updated_at.isoformat(),
                "metadata": {
                    "review_case_id": review_case.id,
                    "source": review_case.source,
                    "suggested_action": review_case.suggested_action,
                },
            }
        )

    return trace_events


def build_orchestration_trace(
    *,
    output: dict[str, Any],
    thread: AgentThread | None,
    checkpoint: AgentThreadCheckpoint | None,
    result: AgentExecutionResult | None = None,
    agent_name: str | None = None,
    route_name: str | None = None,
    confidence: float | None = None,
    timeline_nodes: Sequence[dict[str, Any]] | None = None,
    tool_calls: Sequence[dict[str, Any]] | None = None,
    trace_events: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base_trace = output.get("retrieval_trace")
    trace: dict[str, Any] = dict(base_trace) if isinstance(base_trace, dict) else {}
    resolved_agent_name = result.agent_name if result is not None else str(agent_name or "")
    resolved_route_name = result.route_name if result is not None else str(route_name or "")
    resolved_confidence = result.confidence if result is not None else confidence

    router = dict(trace.get("router") or {})
    if not router:
        router = {
            "domain": thread.domain if thread is not None else "generic",
            "specialist": resolved_agent_name or "generic_policy_agent",
            "confidence": resolved_confidence,
        }

    if result is not None:
        pending_interrupt = (
            dict(thread.pending_interrupt_json or result.interrupt or {})
            if thread
            else dict(result.interrupt or {})
        )
        serialized_timeline_nodes = _serialize_timeline_nodes_from_result(result)
        serialized_tool_calls = _serialize_tool_calls_from_result(result)
    else:
        pending_interrupt = dict(thread.pending_interrupt_json or {}) if thread is not None else {}
        serialized_timeline_nodes = _serialize_timeline_nodes_from_payload(timeline_nodes)
        serialized_tool_calls = _serialize_tool_calls_from_payload(tool_calls)

    trace.update(
        {
            "agent_name": resolved_agent_name,
            "route_name": resolved_route_name,
            "thread_id": thread.id if thread is not None else trace.get("thread_id"),
            "thread_status": thread.status if thread is not None else trace.get("thread_status"),
            "queue_name": output.get("queue_name"),
            "router": router,
            "pending_interrupt": pending_interrupt,
            "latest_checkpoint": serialize_checkpoint_summary(checkpoint),
            "timeline_nodes": serialized_timeline_nodes,
            "tool_calls": serialized_tool_calls,
            "trace_events": list(trace_events or []),
        }
    )
    return trace


def persist_execution_checkpoint(
    session: Session,
    *,
    thread: AgentThread,
    agent_run_id: str,
    result: AgentExecutionResult,
    output_override: dict[str, object] | None = None,
) -> AgentThreadCheckpoint | None:
    if not result.checkpoint_payload:
        return None

    checkpoint = AgentThreadCheckpoint(
        id=str(uuid4()),
        thread_id=thread.id,
        agent_run_id=agent_run_id,
        checkpoint_type=result.checkpoint_type or "engine_adapter_state",
        status="paused" if result.interrupt else "completed",
        state_json=build_checkpoint_state(result, output_override=output_override),
        pending_interrupt_json=dict(result.interrupt or {}),
    )
    session.add(checkpoint)
    session.flush()
    thread.latest_checkpoint_id = checkpoint.id
    session.add(thread)
    return checkpoint


__all__ = [
    "build_checkpoint_state",
    "build_orchestration_trace",
    "build_trace_events",
    "persist_execution_checkpoint",
    "serialize_checkpoint_summary",
]
