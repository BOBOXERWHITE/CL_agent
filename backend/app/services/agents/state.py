from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.agents.engine import TimelineEvent


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
    # P3.7: structured engine events carried through to the route so the
    # ``agent_event`` table gets populated inside the same transaction as
    # ``AgentRun``. Empty when the underlying agent is still on the pre-P3.1
    # code path (e.g. anomaly / ticket_router) or when no events were
    # produced. The route treats the list as the source of truth for
    # structured event replay; ``timeline`` stays as the legacy display view.
    engine_events: list[TimelineEvent] = field(default_factory=list)
    interrupt: dict[str, Any] | None = None
    checkpoint_payload: dict[str, Any] = field(default_factory=dict)
    checkpoint_type: str | None = None
