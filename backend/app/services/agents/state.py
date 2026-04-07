from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TimelineStep:
    node_name: str
    status: str
    detail: str
    timestamp: datetime = field(default_factory=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_name": self.node_name,
            "status": self.status,
            "detail": self.detail,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    status: str
    latency_ms: int
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "input_payload": self.input_payload,
            "output_payload": self.output_payload,
        }


@dataclass(frozen=True)
class AgentExecutionResult:
    agent_name: str
    route_name: str
    status: str
    confidence: float
    requires_human_review: bool
    output: dict[str, Any]
    timeline: list[TimelineStep]
    tool_calls: list[ToolCallRecord]
