"""P8: OpenInference-aligned span helpers for agent / tool / LLM tracing.

OpenInference (https://github.com/Arize-ai/openinference) is the 2025
de-facto standard for LLM / agent OTEL semantic conventions. Arize
Phoenix, LangSmith, Helicone, OpenLLMetry, Datadog and (increasingly)
generic OTEL backends all render spans correctly when these attribute
names are used.

We wrap the existing :func:`app.core.observability.tracing.trace_span`
context manager so:

- Caller code stays simple: ``with agent_span("policy_qa", agent_name=...)``
  is the whole instrumentation; no need to remember attribute keys.
- Attribute names are pinned in ONE place; renaming a key here updates
  every dashboard at once.
- All helpers degrade gracefully to no-op when OTEL isn't initialised —
  product code can sprinkle these freely without try/except.

Span hierarchy in practice
==========================

    agent.policy_supervisor           (kind=AGENT)
      ├─ react.step.1                 (kind=CHAIN)
      │    ├─ llm.react_plan          (kind=LLM)
      │    └─ tool.policy_search      (kind=TOOL)
      │         └─ retriever          (kind=RETRIEVER)
      ├─ react.step.2                 (kind=CHAIN)
      │    └─ llm.react_plan          (kind=LLM)
      └─ llm.answer                   (kind=LLM)

That tree is what Phoenix / LangSmith / Jaeger render as a waterfall —
operators can see "this LLM call belongs to step 2 of this agent for
this tenant" without any extra UI work.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any, Final

from app.core.observability.tracing import _SpanHandle, trace_span

# OpenInference attribute keys. Pinned here rather than imported from
# the openinference-semantic-conventions package because that package
# is an optional dep — most operators install Phoenix / LangSmith via
# their own SDK, not via the convention package. Hardcoding keeps the
# only dep ``opentelemetry-sdk``.
OPENINFERENCE_SPAN_KIND: Final = "openinference.span.kind"


class SpanKind:
    """OpenInference span kinds. Trace backends use this to pick the
    right icon / colour and to enable LLM-specific UI (token bar, cost
    badge, prompt preview). Keep in sync with the upstream enum at
    https://github.com/Arize-ai/openinference/blob/main/python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py."""

    AGENT: Final = "AGENT"
    CHAIN: Final = "CHAIN"
    LLM: Final = "LLM"
    RETRIEVER: Final = "RETRIEVER"
    TOOL: Final = "TOOL"
    RERANKER: Final = "RERANKER"
    EMBEDDING: Final = "EMBEDDING"


# 2 KB stays well under OTLP's per-attribute limit (~4 KB is common but
# not universal; some backends cap at 1 KB). Big payloads usually mean a
# bug — truncate rather than risk silent span drops.
_MAX_ATTR_STR_LEN: Final = 2048


def safe_attr_value(value: Any) -> Any:
    """Convert arbitrary Python values to OTEL-attribute-safe primitives.

    - Primitives (int / float / bool / str under cap) pass through so
      OTEL can preserve typed attributes (the trace UI shows them as
      numbers / booleans).
    - dict / list serialize to compact JSON.
    - Anything else round-trips through ``str()``.
    - All strings are truncated at 2 KB with an ellipsis suffix so a
      runaway prompt body can't blow the attribute size limit.
    """
    if value is None:
        return ""
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_ATTR_STR_LEN:
            return value[: _MAX_ATTR_STR_LEN - 3] + "..."
        return value
    if isinstance(value, dict | list | tuple | set):
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            serialized = str(value)
        if len(serialized) > _MAX_ATTR_STR_LEN:
            return serialized[: _MAX_ATTR_STR_LEN - 3] + "..."
        return serialized
    text = str(value)
    if len(text) > _MAX_ATTR_STR_LEN:
        return text[: _MAX_ATTR_STR_LEN - 3] + "..."
    return text


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def agent_span(
    name: str,
    *,
    agent_name: str,
    question: str | None = None,
    tenant_id: str | None = None,
    customer_id: str | None = None,
    **extra: Any,
) -> Iterator[_SpanHandle]:
    """Top-level span for one agent invocation.

    ``name`` is the SHORT identifier used in the span name (e.g.
    ``"policy_supervisor"`` → ``"agent.policy_supervisor"``).
    ``agent_name`` is the full canonical agent identifier used in
    business logic (e.g. ``"policy_supervisor_agent"``) — both are
    recorded so search-by-either works.
    """
    attrs: dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: SpanKind.AGENT,
        "agent.name": agent_name,
    }
    if tenant_id:
        attrs["tenant.id"] = tenant_id
    if customer_id:
        attrs["customer.id"] = customer_id
    if question is not None:
        attrs["input.value"] = safe_attr_value(question)
    for k, v in extra.items():
        attrs[k] = safe_attr_value(v)
    with trace_span(f"agent.{name}", **attrs) as span:
        yield span


@contextlib.contextmanager
def tool_span(
    *,
    tool_name: str,
    tool_input: Any = None,
    **extra: Any,
) -> Iterator[_SpanHandle]:
    """Wrap a single tool invocation.

    The post-call ``set_attr("tool.status", ...)`` /
    ``set_attr("tool.latency_ms", ...)`` /
    ``set_attr("tool.output", ...)`` calls are the caller's
    responsibility — the helper's job is just to set the kind + name +
    parameters at entry.
    """
    attrs: dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: SpanKind.TOOL,
        "tool.name": tool_name,
    }
    if tool_input is not None:
        attrs["tool.parameters"] = safe_attr_value(tool_input)
    for k, v in extra.items():
        attrs[k] = safe_attr_value(v)
    with trace_span(f"tool.{tool_name}", **attrs) as span:
        yield span


@contextlib.contextmanager
def llm_span(
    *,
    purpose: str,
    model_name: str,
    provider: str = "openai-compatible",
    **extra: Any,
) -> Iterator[_SpanHandle]:
    """Wrap an LLM API call.

    ``purpose`` becomes the span name suffix and lets dashboards group
    by use-case (e.g. ``"react_plan"`` vs ``"answer"`` vs ``"judge"``).
    Token counts + cost should be set via ``span.set_attr`` after the
    HTTP response is parsed:

    .. code-block:: python

        with llm_span(purpose="react_plan", model_name="x", provider="y") as span:
            resp = client.post(...)
            usage = resp.json().get("usage", {})
            span.set_attr("llm.token_count.prompt", usage.get("prompt_tokens", 0))
            span.set_attr("llm.token_count.completion", usage.get("completion_tokens", 0))
    """
    attrs: dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: SpanKind.LLM,
        "llm.model_name": model_name,
        "llm.provider": provider,
    }
    for k, v in extra.items():
        attrs[k] = safe_attr_value(v)
    with trace_span(f"llm.{purpose}", **attrs) as span:
        yield span


@contextlib.contextmanager
def retriever_span(
    *,
    query: str,
    top_k: int | None = None,
    **extra: Any,
) -> Iterator[_SpanHandle]:
    """Wrap a retrieval call. After exit the caller usually sets
    ``retrieval.documents.count`` / ``retrieval.documents.0.id`` / ...
    so the trace UI can show what was retrieved."""
    attrs: dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: SpanKind.RETRIEVER,
        "retrieval.query": safe_attr_value(query),
    }
    if top_k is not None:
        attrs["retrieval.top_k"] = top_k
    for k, v in extra.items():
        attrs[k] = safe_attr_value(v)
    with trace_span("retriever", **attrs) as span:
        yield span


@contextlib.contextmanager
def react_step_span(
    *,
    step: int,
    plan_action: str,
    plan_tool: str | None = None,
    fallback_used: bool = False,
    **extra: Any,
) -> Iterator[_SpanHandle]:
    """One iteration of the ReAct plan-act-observe loop.

    Kind is CHAIN (not AGENT) — the surrounding ``agent_span`` already
    represents the whole agent invocation; each step is a sub-chain
    within it. This matches how LangChain / LangGraph emit their own
    iteration spans.
    """
    attrs: dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: SpanKind.CHAIN,
        "react.step": step,
        "react.plan.action": plan_action,
        "react.plan.fallback_used": fallback_used,
    }
    if plan_tool is not None:
        attrs["react.plan.tool"] = plan_tool
    for k, v in extra.items():
        attrs[k] = safe_attr_value(v)
    with trace_span(f"react.step.{step}", **attrs) as span:
        yield span


__all__ = [
    "OPENINFERENCE_SPAN_KIND",
    "SpanKind",
    "agent_span",
    "llm_span",
    "react_step_span",
    "retriever_span",
    "safe_attr_value",
    "tool_span",
]
