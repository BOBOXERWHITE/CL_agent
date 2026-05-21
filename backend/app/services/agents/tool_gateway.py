from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agents.engine import EventType, TimelineEvent
from app.services.agents.tool_registry import ToolNotRegistered, get_default_registry
from app.services.agents.tool_runner import ToolInvocationResult, get_default_tool_runner


@dataclass(frozen=True)
class GuardedToolResult:
    tool_name: str
    status: str
    latency_ms: int
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    error: str | None
    guardrail_events: list[dict[str, Any]]
    engine_events: list[TimelineEvent]
    interrupted: bool = False


def run_guarded_tool(
    tool_name: str,
    raw_input: dict[str, Any],
    *,
    thread_id: str,
    approved: bool = False,
) -> GuardedToolResult:
    registry = get_default_registry()
    runner = get_default_tool_runner()
    try:
        tool = registry.get(tool_name)
    except ToolNotRegistered as exc:
        return GuardedToolResult(
            tool_name=tool_name,
            status="failed",
            latency_ms=0,
            input_payload=raw_input,
            output_payload={},
            error=str(exc),
            guardrail_events=[
                {
                    "tool_name": tool_name,
                    "decision": "deny",
                    "reason": str(exc),
                    "thread_id": thread_id,
                }
            ],
            engine_events=[],
        )

    risk_level = getattr(tool, "risk_level", "low")
    requires_approval = bool(getattr(tool, "requires_approval", False))
    guardrail_event = {
        "tool_name": tool_name,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "idempotency_scope": getattr(tool, "idempotency_scope", "request"),
        "thread_id": thread_id,
        "decision": "allow",
        "reason": "tool classified as low-risk" if risk_level == "low" else "",
    }
    if (risk_level == "high" or requires_approval) and not approved:
        guardrail_event = {
            **guardrail_event,
            "decision": "interrupt",
            "reason": "tool requires explicit human approval before execution",
        }
        return GuardedToolResult(
            tool_name=tool_name,
            status="interrupted",
            latency_ms=0,
            input_payload=raw_input,
            output_payload={},
            error=guardrail_event["reason"],
            guardrail_events=[guardrail_event],
            engine_events=[
                TimelineEvent(
                    sequence=0,
                    event_type=EventType.PAUSE,
                    node_name="tool_gateway",
                    payload={"tool": tool_name, "reason": guardrail_event["reason"]},
                )
            ],
            interrupted=True,
        )

    result: ToolInvocationResult = runner.run(tool_name, raw_input)
    return GuardedToolResult(
        tool_name=tool_name,
        status=result.status.value,
        latency_ms=result.latency_ms,
        input_payload=result.input_payload,
        output_payload=result.output_payload,
        error=result.error,
        guardrail_events=[guardrail_event],
        engine_events=list(result.events),
    )


__all__ = ["GuardedToolResult", "run_guarded_tool"]
