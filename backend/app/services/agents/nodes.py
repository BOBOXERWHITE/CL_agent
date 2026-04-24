from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from app.services.agents.state import TimelineStep, ToolCallRecord


def append_timeline_step(
    timeline: list[TimelineStep],
    *,
    node_name: str,
    status: str,
    detail: str,
) -> None:
    timeline.append(TimelineStep(node_name=node_name, status=status, detail=detail))


def invoke_tool(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    handler: Callable[..., dict[str, Any]],
) -> ToolCallRecord:
    started_at = perf_counter()
    output_payload = handler(**tool_input)
    latency_ms = int((perf_counter() - started_at) * 1000)
    return ToolCallRecord(
        tool_name=tool_name,
        status="completed",
        latency_ms=latency_ms,
        input_payload=tool_input,
        output_payload=output_payload,
    )
