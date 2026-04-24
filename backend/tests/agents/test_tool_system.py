"""Tests for the P3.5 Tool System — registry + runner + builtins.

Run against the default registry via ``reset_default_registry`` at the
start of each test, then re-import ``tools`` to repopulate. This keeps
tests isolated without a fixture factory.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import BaseModel, Field

from app.services.agents.engine import EventType
from app.services.agents.tool_registry import (
    Tool,
    ToolNotRegistered,
    ToolRegistry,
    ToolRegistryConflict,
)
from app.services.agents.tool_runner import (
    CircuitPolicy,
    RetryPolicy,
    ToolInvocationStatus,
    ToolRunner,
)

# ---------------------------------------------------------------------------
# Fake tools
# ---------------------------------------------------------------------------


class _SumInput(BaseModel):
    a: int = Field(ge=0)
    b: int = Field(ge=0)


class _SumOutput(BaseModel):
    total: int


class _SumTool(Tool):
    name = "sum_tool"
    description = "Add two non-negative ints."
    input_model = _SumInput
    output_model = _SumOutput

    def invoke(self, payload: BaseModel) -> BaseModel:
        assert isinstance(payload, _SumInput)
        return _SumOutput(total=payload.a + payload.b)


class _FlakyInput(BaseModel):
    x: int


class _FlakyOutput(BaseModel):
    ok: bool


class _FlakyTool(Tool):
    """Fails the first N times, then succeeds."""

    name = "flaky_tool"
    description = "Fails until it has been called ``threshold`` times."
    input_model = _FlakyInput
    output_model = _FlakyOutput

    def __init__(self, *, threshold: int) -> None:
        self._threshold = threshold
        self._calls = 0

    def invoke(self, payload: BaseModel) -> BaseModel:
        self._calls += 1
        if self._calls < self._threshold:
            raise RuntimeError(f"flake attempt {self._calls}")
        return _FlakyOutput(ok=True)


class _AlwaysFailsTool(Tool):
    name = "boom"
    description = "Always raises."
    input_model = _FlakyInput
    output_model = _FlakyOutput

    def invoke(self, payload: BaseModel) -> BaseModel:
        raise RuntimeError("kaboom")


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_registry_rejects_non_tool() -> None:
    reg = ToolRegistry()
    with pytest.raises(TypeError):
        reg.register("not a tool")  # type: ignore[arg-type]


def test_registry_rejects_duplicate_name_without_replace() -> None:
    reg = ToolRegistry()
    reg.register(_SumTool())
    with pytest.raises(ToolRegistryConflict):
        reg.register(_SumTool())


def test_registry_allows_replace_on_demand() -> None:
    reg = ToolRegistry()
    reg.register(_SumTool())
    reg.register(_SumTool(), replace=True)  # no error


def test_registry_get_and_has() -> None:
    reg = ToolRegistry()
    reg.register(_SumTool())
    assert reg.has("sum_tool")
    assert isinstance(reg.get("sum_tool"), _SumTool)
    with pytest.raises(ToolNotRegistered):
        reg.get("nonexistent")


def test_describe_all_exposes_json_schemas() -> None:
    reg = ToolRegistry()
    reg.register(_SumTool())
    reg.register(_FlakyTool(threshold=1))
    descriptions = reg.describe_all()
    assert len(descriptions) == 2
    by_name = {d["name"]: d for d in descriptions}
    assert "properties" in by_name["sum_tool"]["input_schema"]
    assert by_name["sum_tool"]["description"]


def test_builtin_tools_registered_by_import() -> None:
    """Importing ``tools`` pre-registers the built-ins."""
    from app.services.agents import tools as tools_module
    from app.services.agents.tool_registry import get_default_registry

    importlib.reload(tools_module)
    registry = get_default_registry()
    assert registry.has("order_lookup")
    assert registry.has("ticket_queue_lookup")


# ---------------------------------------------------------------------------
# Runner — happy path
# ---------------------------------------------------------------------------


def _fresh_runner() -> tuple[ToolRunner, ToolRegistry]:
    reg = ToolRegistry()
    runner = ToolRunner(
        reg,
        retry=RetryPolicy(attempts=1),
        circuit=CircuitPolicy(failure_threshold=0),  # disable breaker
    )
    return runner, reg


def test_runner_completes_happy_path() -> None:
    runner, reg = _fresh_runner()
    reg.register(_SumTool())
    result = runner.run("sum_tool", {"a": 2, "b": 3})
    assert result.status == ToolInvocationStatus.COMPLETED
    assert result.output_payload == {"total": 5}
    assert result.attempts == 1
    assert result.error is None
    # Emits matching START + END events.
    kinds = [e.event_type for e in result.events]
    assert EventType.TOOL_CALL_START in kinds
    assert EventType.TOOL_CALL_END in kinds


def test_runner_unknown_tool_returns_failure() -> None:
    runner, _ = _fresh_runner()
    result = runner.run("ghost_tool", {})
    assert result.status == ToolInvocationStatus.FAILED
    assert "ghost_tool" in (result.error or "")


# ---------------------------------------------------------------------------
# Runner — input validation
# ---------------------------------------------------------------------------


def test_runner_rejects_input_failing_pydantic() -> None:
    runner, reg = _fresh_runner()
    reg.register(_SumTool())
    # a=-1 fails ge=0
    result = runner.run("sum_tool", {"a": -1, "b": 3})
    assert result.status == ToolInvocationStatus.VALIDATION_ERROR
    assert result.output_payload == {}
    # Tool was never invoked -> no 'total' surfaced.
    assert result.error is not None


def test_runner_rejects_missing_required_field() -> None:
    runner, reg = _fresh_runner()
    reg.register(_SumTool())
    result = runner.run("sum_tool", {"a": 1})  # b missing
    assert result.status == ToolInvocationStatus.VALIDATION_ERROR


# ---------------------------------------------------------------------------
# Runner — retry
# ---------------------------------------------------------------------------


def test_runner_retries_flaky_tool_and_succeeds() -> None:
    reg = ToolRegistry()
    reg.register(_FlakyTool(threshold=3))  # 2 fails then OK
    runner = ToolRunner(
        reg,
        retry=RetryPolicy(attempts=3, base_backoff_seconds=0.0),  # no wait in tests
        circuit=CircuitPolicy(failure_threshold=0),
    )
    result = runner.run("flaky_tool", {"x": 1}, sleep_fn=lambda _s: None)
    assert result.status == ToolInvocationStatus.COMPLETED
    assert result.attempts == 3
    assert result.output_payload == {"ok": True}


def test_runner_gives_up_after_exhausting_attempts() -> None:
    reg = ToolRegistry()
    reg.register(_AlwaysFailsTool())
    runner = ToolRunner(
        reg,
        retry=RetryPolicy(attempts=2, base_backoff_seconds=0.0),
        circuit=CircuitPolicy(failure_threshold=0),
    )
    result = runner.run("boom", {"x": 1}, sleep_fn=lambda _s: None)
    assert result.status == ToolInvocationStatus.FAILED
    assert result.attempts == 2
    assert "kaboom" in (result.error or "")


def test_runner_honors_custom_backoff_schedule() -> None:
    """Runner waits between retries using the provided sleep_fn."""
    reg = ToolRegistry()
    reg.register(_AlwaysFailsTool())
    runner = ToolRunner(
        reg,
        retry=RetryPolicy(attempts=3, base_backoff_seconds=0.1, backoff_factor=2.0),
        circuit=CircuitPolicy(failure_threshold=0),
    )
    slept: list[float] = []
    runner.run("boom", {"x": 1}, sleep_fn=slept.append)
    # 2 retries -> 2 sleeps; durations 0.1 then 0.2.
    assert slept == [0.1, 0.2]


# ---------------------------------------------------------------------------
# Runner — circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_opens_after_threshold_failures() -> None:
    reg = ToolRegistry()
    reg.register(_AlwaysFailsTool())
    runner = ToolRunner(
        reg,
        retry=RetryPolicy(attempts=1),
        circuit=CircuitPolicy(failure_threshold=2, cooldown_seconds=60.0),
    )

    # First two calls record failures, breaker opens on the 2nd.
    r1 = runner.run("boom", {"x": 1}, sleep_fn=lambda _: None)
    r2 = runner.run("boom", {"x": 1}, sleep_fn=lambda _: None)
    assert r1.status == ToolInvocationStatus.FAILED
    assert r2.status == ToolInvocationStatus.FAILED

    # Third call is short-circuited.
    r3 = runner.run("boom", {"x": 1}, sleep_fn=lambda _: None)
    assert r3.status == ToolInvocationStatus.CIRCUIT_OPEN
    assert r3.attempts == 0


def test_circuit_reopens_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """After cooldown elapses, the breaker gives the tool another shot."""
    import app.services.agents.tool_runner as runner_module

    # Fake monotonic clock so we can fast-forward.
    now = [1000.0]

    def fake_monotonic() -> float:
        return now[0]

    monkeypatch.setattr(runner_module, "monotonic", fake_monotonic)

    reg = ToolRegistry()
    reg.register(_AlwaysFailsTool())
    runner = ToolRunner(
        reg,
        retry=RetryPolicy(attempts=1),
        circuit=CircuitPolicy(failure_threshold=1, cooldown_seconds=5.0),
    )

    # One failure opens the circuit immediately.
    runner.run("boom", {"x": 1}, sleep_fn=lambda _: None)
    assert runner.run("boom", {"x": 1}, sleep_fn=lambda _: None).status == (
        ToolInvocationStatus.CIRCUIT_OPEN
    )

    # Fast-forward past cooldown.
    now[0] += 6.0
    # Next call should try again (fails, but was attempted).
    result = runner.run("boom", {"x": 1}, sleep_fn=lambda _: None)
    assert result.status == ToolInvocationStatus.FAILED
    assert result.attempts == 1


def test_success_resets_failure_count() -> None:
    reg = ToolRegistry()
    flaky = _FlakyTool(threshold=2)  # first call fails, then OK
    reg.register(flaky)
    runner = ToolRunner(
        reg,
        retry=RetryPolicy(attempts=1),
        circuit=CircuitPolicy(failure_threshold=2, cooldown_seconds=60.0),
    )

    # 1st call fails (attempts=1, no retry)
    r1 = runner.run("flaky_tool", {"x": 1}, sleep_fn=lambda _: None)
    assert r1.status == ToolInvocationStatus.FAILED
    # 2nd call succeeds (flaky threshold=2 means 1 failure, then success)
    r2 = runner.run("flaky_tool", {"x": 1}, sleep_fn=lambda _: None)
    assert r2.status == ToolInvocationStatus.COMPLETED
    # Circuit is NOT open despite the prior failure, because success reset.
    assert not runner._circuit.is_open("flaky_tool")


# ---------------------------------------------------------------------------
# Built-in tools -- behaviour preserved from legacy free functions
# ---------------------------------------------------------------------------


def test_order_lookup_tool_returns_sandbox_shape() -> None:
    from app.services.agents.tools import OrderLookupInput, OrderLookupTool

    tool = OrderLookupTool()
    result = tool.invoke(OrderLookupInput(ticket_id="t-abc"))
    assert result.model_dump() == {
        "ticket_id": "t-abc",
        "order_status": "pending_review",
        "source": "sandbox-order-service",
    }


def test_ticket_queue_lookup_hotel_above_threshold_goes_to_finance() -> None:
    from app.services.agents.tools import (
        TicketInfo,
        TicketQueueLookupInput,
        TicketQueueLookupTool,
    )

    tool = TicketQueueLookupTool()
    result = tool.invoke(
        TicketQueueLookupInput(
            ticket=TicketInfo(
                ticket_id="t-001",
                expense_type="hotel",
                city="北京",
                amount=1200.0,
            )
        )
    )
    assert result.queue_name == "finance-review"
    assert "酒店" in result.reason


def test_ticket_queue_lookup_huge_amount_goes_to_senior() -> None:
    from app.services.agents.tools import (
        TicketInfo,
        TicketQueueLookupInput,
        TicketQueueLookupTool,
    )

    tool = TicketQueueLookupTool()
    result = tool.invoke(
        TicketQueueLookupInput(ticket=TicketInfo(expense_type="travel", amount=6000.0))
    )
    assert result.queue_name == "senior-approval"


def test_ticket_queue_lookup_default_route() -> None:
    from app.services.agents.tools import (
        TicketInfo,
        TicketQueueLookupInput,
        TicketQueueLookupTool,
    )

    tool = TicketQueueLookupTool()
    result = tool.invoke(
        TicketQueueLookupInput(ticket=TicketInfo(expense_type="meal", amount=300.0))
    )
    assert result.queue_name == "ops-review"


def test_legacy_shims_still_work() -> None:
    """pre-Phase-3 free-function imports must keep working."""
    from app.services.agents.tools import lookup_order_details, lookup_ticket_queue

    order = lookup_order_details("ticket-xyz")
    assert order["ticket_id"] == "ticket-xyz"

    queue = lookup_ticket_queue({"expense_type": "hotel", "city": "上海", "amount": 1500})
    assert queue["queue_name"] == "finance-review"
