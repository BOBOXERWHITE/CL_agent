"""Policy wrapper around tool invocations (P3.5).

The Runner is where failure handling lives so individual ``Tool``
implementations stay dumb + testable. Responsibilities:

- **Input validation**: deserialize the raw dict the agent produced
  through the tool's ``input_model`` (Pydantic). Bad inputs short-circuit
  before the tool runs and surface as a ``validation_error`` status.
- **Retry with exponential backoff**: transient failures (any
  ``Exception`` short of the explicit non-retryable list) get retried
  up to N times with backoff. Non-retryables fail fast.
- **Circuit breaker**: per-tool failure count + cooldown. Once failures
  cross a threshold within a window, subsequent calls short-circuit
  (``circuit_open`` status) until the cooldown elapses. This protects
  the LLM from hammering a flapping upstream and blowing the budget.
- **Timing + events**: emits ``TOOL_CALL_START`` / ``TOOL_CALL_END``
  TimelineEvents consumable by the engine (P3.1) and persists enough
  context for ``ToolCallLog`` rows (P1.5 audit).
- **Never raises**: the Runner always returns a ``ToolInvocationResult``.
  Calling agent code should check the status field; a tool failure is
  a normal state machine transition, not an exception.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic, perf_counter, sleep
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services.agents.engine import EventType, TimelineEvent
from app.services.agents.tool_registry import ToolNotRegistered, ToolRegistry

_log = logging.getLogger(__name__)


class ToolInvocationStatus(str, Enum):
    """End state of a single tool call."""

    COMPLETED = "completed"
    VALIDATION_ERROR = "validation_error"  # input didn't match input_model
    FAILED = "failed"  # tool raised after exhausting retries
    CIRCUIT_OPEN = "circuit_open"  # breaker refused to call


@dataclass(frozen=True)
class ToolInvocationResult:
    """What the Runner returns for every call.

    Carries the ``ToolCallRecord``-equivalent fields (tool_name, status,
    latency_ms, input, output) plus a list of timeline events the
    engine can merge into its own event stream. This way a graph node
    just does ``runner.run(...)`` and appends ``result.events`` to its
    own ``NodeResult.events``.
    """

    tool_name: str
    status: ToolInvocationStatus
    latency_ms: int
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    attempts: int
    error: str | None
    events: list[TimelineEvent] = field(default_factory=list)


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff profile for the Runner.

    ``attempts`` is the *total* attempt count (not retries after the
    first try). 1 = no retry. The default 3 is a safe "try twice more"
    pattern that handles transient upstream blips without multiplying
    flaky-test wait time.
    """

    attempts: int = 3
    base_backoff_seconds: float = 0.2  # first retry after 0.2s
    backoff_factor: float = 2.0  # then 0.4, 0.8, ...
    max_backoff_seconds: float = 5.0

    def backoff(self, attempt_index: int) -> float:
        """Backoff before the ``attempt_index``-th retry (0-based after 1st)."""
        computed = self.base_backoff_seconds * (self.backoff_factor**attempt_index)
        return min(computed, self.max_backoff_seconds)


@dataclass(frozen=True)
class CircuitPolicy:
    """Circuit breaker config.

    - After ``failure_threshold`` consecutive failures, the breaker
      opens and rejects calls until ``cooldown_seconds`` elapses.
    - A successful call resets the failure count to 0.
    - ``failure_threshold=0`` disables the breaker (tests use this).
    """

    failure_threshold: int = 5
    cooldown_seconds: float = 30.0


class _CircuitBreaker:
    """Process-wide per-tool circuit breaker state.

    Thread-safe (Lock guards counters); lives on the Runner instance
    so tests can make fresh Runners with clean state. In production
    there's one Runner per process via ``get_default_tool_runner()``.
    """

    def __init__(self, policy: CircuitPolicy) -> None:
        self._policy = policy
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, tool_name: str) -> bool:
        if self._policy.failure_threshold <= 0:
            return False
        with self._lock:
            opened_at = self._opened_at.get(tool_name)
            if opened_at is None:
                return False
            if monotonic() - opened_at >= self._policy.cooldown_seconds:
                # Cooldown elapsed: half-open, give the tool another chance.
                self._opened_at.pop(tool_name, None)
                self._failures[tool_name] = 0
                return False
            return True

    def record_success(self, tool_name: str) -> None:
        with self._lock:
            self._failures[tool_name] = 0
            self._opened_at.pop(tool_name, None)

    def record_failure(self, tool_name: str) -> None:
        if self._policy.failure_threshold <= 0:
            return
        with self._lock:
            count = self._failures.get(tool_name, 0) + 1
            self._failures[tool_name] = count
            if count >= self._policy.failure_threshold:
                self._opened_at[tool_name] = monotonic()


class ToolRunner:
    """Sync invocation wrapper for a ``Tool``.

    The runner does NOT own the registry; callers pass the tool name
    and raw input dict, the runner looks it up, validates, retries,
    measures, emits events. This keeps the runner stateless aside from
    circuit-breaker counters.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        retry: RetryPolicy | None = None,
        circuit: CircuitPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._retry = retry or RetryPolicy()
        self._circuit = _CircuitBreaker(circuit or CircuitPolicy())

    def run(
        self,
        tool_name: str,
        raw_input: dict[str, Any],
        *,
        sleep_fn: callable = sleep,  # injectable so tests don't actually sleep
    ) -> ToolInvocationResult:
        """Invoke ``tool_name`` with ``raw_input``; never raise."""
        started = perf_counter()
        events: list[TimelineEvent] = [
            TimelineEvent(
                sequence=0,
                event_type=EventType.TOOL_CALL_START,
                node_name="tool_runner",
                payload={"tool": tool_name, "input": raw_input},
            )
        ]

        # ---- resolve tool ------------------------------------------------
        try:
            tool = self._registry.get(tool_name)
        except ToolNotRegistered as exc:
            return self._finalize_error(
                tool_name,
                raw_input,
                ToolInvocationStatus.FAILED,
                str(exc),
                attempts=0,
                started=started,
                events=events,
            )

        # ---- circuit check ----------------------------------------------
        if self._circuit.is_open(tool_name):
            return self._finalize_error(
                tool_name,
                raw_input,
                ToolInvocationStatus.CIRCUIT_OPEN,
                "circuit breaker open for this tool",
                attempts=0,
                started=started,
                events=events,
            )

        # ---- validate input ---------------------------------------------
        try:
            payload = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            self._circuit.record_failure(tool_name)
            return self._finalize_error(
                tool_name,
                raw_input,
                ToolInvocationStatus.VALIDATION_ERROR,
                str(exc),
                attempts=0,
                started=started,
                events=events,
            )

        # ---- invoke with retry ------------------------------------------
        last_error: Exception | None = None
        output: BaseModel | None = None
        attempts_made = 0
        for attempt in range(self._retry.attempts):
            attempts_made = attempt + 1
            try:
                output = tool.invoke(payload)
                break
            except Exception as exc:
                last_error = exc
                _log.warning(
                    "tool_invocation_failed",
                    extra={
                        "tool": tool_name,
                        "attempt": attempts_made,
                        "error": str(exc),
                    },
                )
                if attempt < self._retry.attempts - 1:
                    sleep_fn(self._retry.backoff(attempt))

        if output is None:
            assert last_error is not None, "output==None implies last_error set"
            self._circuit.record_failure(tool_name)
            return self._finalize_error(
                tool_name,
                raw_input,
                ToolInvocationStatus.FAILED,
                str(last_error),
                attempts=attempts_made,
                started=started,
                events=events,
            )

        # ---- success path ------------------------------------------------
        self._circuit.record_success(tool_name)
        output_dict = output.model_dump()
        latency_ms = int((perf_counter() - started) * 1000)
        events.append(
            TimelineEvent(
                sequence=0,
                event_type=EventType.TOOL_CALL_END,
                node_name="tool_runner",
                payload={
                    "tool": tool_name,
                    "status": ToolInvocationStatus.COMPLETED.value,
                    "attempts": attempts_made,
                    "latency_ms": latency_ms,
                },
            )
        )
        return ToolInvocationResult(
            tool_name=tool_name,
            status=ToolInvocationStatus.COMPLETED,
            latency_ms=latency_ms,
            input_payload=raw_input,
            output_payload=output_dict,
            attempts=attempts_made,
            error=None,
            events=events,
        )

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _finalize_error(
        tool_name: str,
        raw_input: dict[str, Any],
        status: ToolInvocationStatus,
        error: str,
        *,
        attempts: int,
        started: float,
        events: list[TimelineEvent],
    ) -> ToolInvocationResult:
        latency_ms = int((perf_counter() - started) * 1000)
        events.append(
            TimelineEvent(
                sequence=0,
                event_type=EventType.TOOL_CALL_END,
                node_name="tool_runner",
                payload={
                    "tool": tool_name,
                    "status": status.value,
                    "attempts": attempts,
                    "latency_ms": latency_ms,
                    "error": error,
                },
            )
        )
        return ToolInvocationResult(
            tool_name=tool_name,
            status=status,
            latency_ms=latency_ms,
            input_payload=raw_input,
            output_payload={},
            attempts=attempts,
            error=error,
            events=events,
        )


# ---------------------------------------------------------------------------
# Default runner (lazy singleton)
# ---------------------------------------------------------------------------
#
# Convenience for callers that don't care about customising retry /
# circuit policies. Tests construct their own Runner with tight
# policies (attempts=1, no circuit) to keep execution fast.

_default_runner: ToolRunner | None = None


def get_default_tool_runner() -> ToolRunner:
    global _default_runner
    if _default_runner is None:
        from app.services.agents.tool_registry import get_default_registry

        _default_runner = ToolRunner(get_default_registry())
    return _default_runner


def reset_default_tool_runner() -> None:
    """Drop the lazy runner. Tests call this to reset circuit-breaker state."""
    global _default_runner
    _default_runner = None


__all__ = [
    "CircuitPolicy",
    "RetryPolicy",
    "ToolInvocationResult",
    "ToolInvocationStatus",
    "ToolRunner",
    "get_default_tool_runner",
    "reset_default_tool_runner",
]
