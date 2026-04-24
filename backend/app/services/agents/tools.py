"""Built-in Tool implementations (P3.5).

This file used to hold a handful of plain functions. It now hosts
``Tool`` subclasses (``tool_registry.Tool``) that carry Pydantic input /
output schemas so the ReAct plan prompt can describe them to the LLM
at runtime.

Backward compatibility
----------------------

The pre-Phase-3 ``lookup_order_details`` / ``lookup_ticket_queue`` free
functions are retained as thin adapters so the legacy
``ticket_router_graph`` / tests that import them keep working. New
nodes should go through ``get_default_tool_runner().run(name, input)``.

Registration
------------

At module import time we register every built-in tool into the default
registry. Importing this module once (via the engine bootstrap) pre-
populates the runner; tests can call ``reset_default_registry`` and
re-register custom fakes without polluting global state.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.agents.tool_registry import (
    Tool,
    ToolRegistryConflict,
    get_default_registry,
)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
#
# Each tool has one request model + one response model. Keep them small
# and flat so the LLM's prompt stays short.


class OrderLookupInput(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=64)


class OrderLookupOutput(BaseModel):
    ticket_id: str
    order_status: str
    source: str


class TicketInfo(BaseModel):
    """The shape of the ``ticket`` dict we have across the codebase."""

    ticket_id: str | None = None
    expense_type: str = ""
    city: str = ""
    amount: float = 0.0
    status: str = "pending_review"


class TicketQueueLookupInput(BaseModel):
    ticket: TicketInfo


class TicketQueueLookupOutput(BaseModel):
    queue_name: str
    reason: str


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class OrderLookupTool(Tool):
    """Stub order-lookup; returns a canned shape until the real ERP
    integration lands. Kept behaviour-identical to the old
    ``lookup_order_details`` so migrated graphs don't regress.
    """

    name = "order_lookup"
    description = "Look up an order's current status by ticket id."
    input_model = OrderLookupInput
    output_model = OrderLookupOutput

    def invoke(self, payload: BaseModel) -> BaseModel:
        assert isinstance(payload, OrderLookupInput)
        return OrderLookupOutput(
            ticket_id=payload.ticket_id,
            order_status="pending_review",
            source="sandbox-order-service",
        )


class PolicySearchInput(BaseModel):
    question: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)


class PolicySearchCitation(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    snippet: str
    score: float


class PolicySearchOutput(BaseModel):
    answer: str
    confidence: float
    citations: list[PolicySearchCitation]
    retrieval_mode: str
    prompt_template_id: str | None = None


class PolicySearchTool(Tool):
    """Policy knowledge retrieval + answer generation via RAG.

    Thin wrapper around ``rag.query_engine.answer_policy_question`` so the
    ReAct policy graph (P3.3) can invoke it through the same
    ``tool_runner`` machinery the other tools use -- meaning retries,
    circuit breaker, and structured events apply to the RAG call too.
    """

    name = "policy_search"
    description = (
        "Search the tenant's policy knowledge base and generate a grounded answer "
        "with citations. Use this for any travel-policy question."
    )
    input_model = PolicySearchInput
    output_model = PolicySearchOutput

    def invoke(self, payload: BaseModel) -> BaseModel:
        assert isinstance(payload, PolicySearchInput)
        # Local import avoids a module-load cycle: query_engine may
        # ultimately trace back through RAG → cache → config.
        from app.services.rag.query_engine import answer_policy_question

        result = answer_policy_question(
            question=payload.question,
            tenant_id=payload.tenant_id,
            customer_id=payload.customer_id,
        )
        citations = [
            PolicySearchCitation(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                snippet=c.snippet,
                score=c.score,
            )
            for c in result.citations
        ]
        return PolicySearchOutput(
            answer=result.answer,
            confidence=result.confidence,
            citations=citations,
            retrieval_mode=result.retrieval_trace.mode,
            prompt_template_id=result.prompt_template_id,
        )


class TicketQueueLookupTool(Tool):
    """Decide which review queue a ticket belongs in.

    Business rules are an exact port of the legacy free function so the
    old ticket_router_graph behaviour is preserved byte-for-byte. When
    we wire it into a real ReAct loop (P3.3+), the rules are easy to
    extend without touching callers.
    """

    name = "ticket_queue_lookup"
    description = (
        "Route a reimbursement ticket to the right review queue based on amount and expense type."
    )
    input_model = TicketQueueLookupInput
    output_model = TicketQueueLookupOutput

    def invoke(self, payload: BaseModel) -> BaseModel:
        assert isinstance(payload, TicketQueueLookupInput)
        ticket = payload.ticket
        expense_type = ticket.expense_type.lower()
        city = ticket.city
        amount = ticket.amount

        if expense_type == "hotel" and amount > 1000:
            return TicketQueueLookupOutput(
                queue_name="finance-review",
                reason=f"{city}酒店费用超出酒店标准，需财务复核。",
            )
        if amount > 5000:
            return TicketQueueLookupOutput(
                queue_name="senior-approval",
                reason="金额超过高额审批阈值，需高级审批。",
            )
        return TicketQueueLookupOutput(
            queue_name="ops-review",
            reason="命中常规人工复核队列。",
        )


# ---------------------------------------------------------------------------
# Legacy adapters (pre-Phase-3 callers)
# ---------------------------------------------------------------------------
#
# The old free-function API is retained so pre-existing graphs / tests
# keep working while we migrate them to the new Runner-based path.


def lookup_order_details(ticket_id: str) -> dict[str, Any]:
    """Legacy shim; new code should go through ``ToolRunner``."""
    return OrderLookupTool().invoke(OrderLookupInput(ticket_id=ticket_id)).model_dump()


def lookup_ticket_queue(ticket: dict[str, Any]) -> dict[str, Any]:
    """Legacy shim; new code should go through ``ToolRunner``."""
    return (
        TicketQueueLookupTool()
        .invoke(TicketQueueLookupInput(ticket=TicketInfo.model_validate(ticket)))
        .model_dump()
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
#
# Called once at module import time. Idempotent (registration errors
# are swallowed) so re-importing under pytest reloads doesn't break.

_BUILTIN_TOOLS: tuple[type[Tool], ...] = (
    OrderLookupTool,
    TicketQueueLookupTool,
    PolicySearchTool,
)


def _register_builtin_tools() -> None:
    registry = get_default_registry()
    for tool_cls in _BUILTIN_TOOLS:
        try:
            registry.register(tool_cls())
        except ToolRegistryConflict:
            # Already registered (module re-imported). Fine.
            pass


_register_builtin_tools()


__all__ = [
    "OrderLookupInput",
    "OrderLookupOutput",
    "OrderLookupTool",
    "PolicySearchCitation",
    "PolicySearchInput",
    "PolicySearchOutput",
    "PolicySearchTool",
    "TicketInfo",
    "TicketQueueLookupInput",
    "TicketQueueLookupOutput",
    "TicketQueueLookupTool",
    "lookup_order_details",
    "lookup_ticket_queue",
]
