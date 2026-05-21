"""P7 Phase C: ``call_agent`` Tool — let any agent invoke another agent.

Wraps the existing per-agent ``execute_*`` entry points in a single
:class:`Tool` so the ReAct planner (Phase B) — or any other caller with
access to the tool registry — can pick "delegate to another domain
specialist" from its action space.

Guardrails baked in:

1. **Off by default**: ``ensure_agent_as_tool_registration()`` is a
   no-op unless ``settings.agent_as_tool_enabled`` is True. The tool
   never lands in the default registry in fresh deployments, so the
   ReAct planner's allow-list cannot accidentally surface it.
2. **Recursion bound**: an internal :class:`contextvars.ContextVar`
   tracks per-request call depth. The N+1th invocation returns a
   ``status="failed"`` :class:`CallAgentOutput` instead of recursing,
   capping cost at ``agent_as_tool_max_depth`` * single-agent cost.
3. **Self-delegation refused**: an agent calling itself bypasses the
   tool runner and returns an error verdict immediately — that path
   is a guaranteed infinite loop until the depth cap, refusing up
   front is cheaper.
4. **Tenant scope propagated**: every nested call MUST carry the
   outer call's tenant_id + customer_id. Pydantic enforces non-empty
   fields; the wrapper forwards them verbatim, no implicit fallback.

The Tool's I/O schemas are Pydantic so the ReAct planner sees a
machine-readable contract (input description) and the tool runner
validates the LLM's args before invocation — same defence-in-depth as
every other registered tool.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.agents.anomaly_graph import execute_anomaly_graph
from app.services.agents.policy_supervisor import execute_policy_supervisor
from app.services.agents.state import AgentExecutionResult
from app.services.agents.ticket_router_graph import execute_ticket_router_graph
from app.services.agents.tool_registry import (
    Tool,
    ToolRegistryConflict,
    get_default_registry,
)

_log = logging.getLogger(__name__)

# Per-request recursion counter. ContextVar (not threading.local!) so it
# behaves correctly under asyncio AND under pytest's monkeypatched
# get_settings without leaking state across tests.
AGENT_CALL_DEPTH_CONTEXT: ContextVar[int] = ContextVar("agent_call_depth", default=0)


# Public names the ReAct planner's allow-list can include. The mapping
# below ties each name to the right ``execute_*`` function so a typo
# in either side raises at startup, not at the first call.
_AGENT_NAME_TO_EXECUTOR_AGENT: dict[str, str] = {
    "policy_qa": "policy_supervisor_agent",
    "ticket_triage": "ticket_router_agent",
    "order_anomaly": "order_anomaly_agent",
}

_AGENT_KEYS = tuple(_AGENT_NAME_TO_EXECUTOR_AGENT.keys())


class CallAgentInput(BaseModel):
    """Schema for ``call_agent`` invocations.

    ``caller_agent_name`` is required so the self-delegation guard can
    refuse cycles. Callers should pass the ``agent_name`` of the agent
    that owns the currently-executing ReAct loop (e.g. the policy
    supervisor passes ``"policy_supervisor_agent"`` here when it
    delegates out).
    """

    agent_name: Literal["policy_qa", "ticket_triage", "order_anomaly"] = Field(
        description=(
            "Target agent to invoke. Must be one of: policy_qa, ticket_triage, order_anomaly."
        ),
    )
    question: str = Field(
        min_length=1,
        description="The question or task to hand off to the target agent.",
    )
    tenant_id: str = Field(min_length=1, description="Tenant scope for the inner call.")
    customer_id: str = Field(min_length=1, description="Customer scope for the inner call.")
    caller_agent_name: str = Field(
        min_length=1,
        description=(
            "Name of the agent making this call (for self-delegation guard and observability)."
        ),
    )


class CallAgentOutput(BaseModel):
    """Verdict from a ``call_agent`` invocation.

    ``status="failed"`` covers both guard refusals (recursion / self /
    unknown name) and downstream agent failures. ``error`` is a short
    human-readable reason; the planner prompt includes it on the next
    cycle so the LLM can decide to give up.
    """

    agent_name: str
    status: str
    answer: str = ""
    confidence: float = 0.0
    citations: list[dict[str, Any]] = Field(default_factory=list)
    requires_human_review: bool = False
    depth: int = 0
    error: str = ""


def _refusal(*, agent_name: str, depth: int, error: str) -> CallAgentOutput:
    return CallAgentOutput(
        agent_name=agent_name,
        status="failed",
        depth=depth,
        error=error,
    )


def _to_output(result: AgentExecutionResult, *, depth: int) -> CallAgentOutput:
    output = result.output or {}
    return CallAgentOutput(
        agent_name=result.agent_name,
        status=result.status,
        answer=str(output.get("answer", "")),
        confidence=float(result.confidence),
        citations=list(output.get("citations", []) or []),
        requires_human_review=bool(result.requires_human_review),
        depth=depth,
        error="",
    )


class CallAgentTool(Tool):
    """``call_agent`` — invoke another agent as a tool.

    The ReAct planner sees this in its allow-list (when
    ``AGENT_AS_TOOL_ENABLED=true``) and can choose to delegate the
    current question to a specialist agent. The recursion guard caps
    cumulative LLM cost at ``agent_as_tool_max_depth`` per request.
    """

    name: ClassVar[str] = "call_agent"
    description: ClassVar[str] = (
        "Delegate the current question to another specialist agent. "
        "Pick this when the current agent's domain cannot answer alone "
        "(e.g. ticket processing needs a policy lookup). Capped at a "
        "configurable nested-call depth to prevent cost runaway."
    )
    input_model: ClassVar[type[BaseModel]] = CallAgentInput
    output_model: ClassVar[type[BaseModel]] = CallAgentOutput
    risk_level: ClassVar[str] = "medium"
    requires_approval: ClassVar[bool] = False
    idempotency_scope: ClassVar[str] = "request"

    def invoke(self, payload: BaseModel) -> CallAgentOutput:
        if not isinstance(payload, CallAgentInput):  # pragma: no cover - defensive
            raise TypeError(f"CallAgentTool expects CallAgentInput, got {type(payload).__name__}")

        settings = get_settings()
        max_depth = settings.agent_as_tool_max_depth
        current_depth = AGENT_CALL_DEPTH_CONTEXT.get()
        next_depth = current_depth + 1

        # Refusal #1: depth cap. Reporting depth=next_depth (not
        # current_depth) makes the cap level visible in observability.
        if next_depth > max_depth:
            _log.warning(
                "agent_as_tool refused: max depth %d exceeded by call to %s",
                max_depth,
                payload.agent_name,
            )
            return _refusal(
                agent_name=_AGENT_NAME_TO_EXECUTOR_AGENT.get(
                    payload.agent_name, payload.agent_name
                ),
                depth=next_depth,
                error=f"refused: max depth {max_depth} exceeded",
            )

        # Refusal #2: self-delegation. Cheaper to refuse than to
        # recurse until the depth cap.
        target_executor_name = _AGENT_NAME_TO_EXECUTOR_AGENT[payload.agent_name]
        if payload.caller_agent_name == target_executor_name:
            _log.warning(
                "agent_as_tool refused: %s tried to delegate to itself",
                payload.caller_agent_name,
            )
            return _refusal(
                agent_name=target_executor_name,
                depth=next_depth,
                error="refused: self-delegation would loop",
            )

        token = AGENT_CALL_DEPTH_CONTEXT.set(next_depth)
        try:
            result = _dispatch(
                target_agent=payload.agent_name,
                question=payload.question,
                tenant_id=payload.tenant_id,
                customer_id=payload.customer_id,
                request_id=f"call-agent-depth-{next_depth}",
            )
            return _to_output(result, depth=next_depth)
        finally:
            AGENT_CALL_DEPTH_CONTEXT.reset(token)


def _dispatch(
    *,
    target_agent: str,
    question: str,
    tenant_id: str,
    customer_id: str,
    request_id: str,
) -> AgentExecutionResult:
    """Route to the appropriate ``execute_*`` function.

    Keeps the per-agent calling convention encapsulated here so the
    Tool itself doesn't need to know which agents take which kwargs.
    """
    if target_agent == "policy_qa":
        return execute_policy_supervisor(
            question=question,
            tenant_id=tenant_id,
            customer_id=customer_id,
            thread_id=request_id,
            run_id=request_id,
            user_id=customer_id,
            route_name="policy_qa",
            base_timeline=[],
        )
    if target_agent == "ticket_triage":
        return execute_ticket_router_graph(
            question=question,
            ticket={"tenant_id": tenant_id, "customer_id": customer_id},
            route_name="ticket_triage",
            base_timeline=[],
        )
    if target_agent == "order_anomaly":
        return execute_anomaly_graph(
            question=question,
            route_name="order_anomaly",
            base_timeline=[],
        )
    # Should be unreachable because Pydantic Literal filters at the
    # input boundary, but if someone bypasses validation this still
    # fails loud instead of silently mis-routing.
    raise ValueError(f"unknown target_agent: {target_agent!r}")


def ensure_agent_as_tool_registration() -> None:
    """Register the ``call_agent`` tool if and only if the feature flag is on.

    Idempotent so repeated calls (e.g. from FastAPI lifespan + a unit
    test setup) don't raise ToolRegistryConflict. Callers can invoke
    this at startup; the registry stays clean when the flag is off.
    """
    if not get_settings().agent_as_tool_enabled:
        return
    registry = get_default_registry()
    if registry.has(CallAgentTool.name):
        return
    try:
        registry.register(CallAgentTool())
    except ToolRegistryConflict:
        # Race-condition safety: another import path registered first.
        pass


__all__ = [
    "AGENT_CALL_DEPTH_CONTEXT",
    "CallAgentInput",
    "CallAgentOutput",
    "CallAgentTool",
    "ensure_agent_as_tool_registration",
]
