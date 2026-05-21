"""P8: tests for the agent-tracing helpers that wrap ``trace_span`` with
OpenInference semantic conventions.

OpenInference (https://github.com/Arize-ai/openinference) is the de-facto
standard for LLM / agent OTEL semantic conventions in 2025 — Phoenix,
LangSmith, Arize, Helicone, OpenLLMetry and Datadog all render spans
nicely when these attribute names are used.

Critical invariants:

1. Each helper sets ``openinference.span.kind`` to the right value so
   the trace UI categorises the span (AGENT / TOOL / LLM / RETRIEVER).
2. The span name follows a stable convention (``agent.<name>``,
   ``tool.<name>``, ``llm.<purpose>``) so dashboards can pattern-match.
3. Caller-supplied attrs (tenant_id, model_name, tool input/output,
   token counts) are forwarded to the underlying OTEL span verbatim.
4. Nested spans preserve parent-child relationships so the trace tree
   is correct: agent → react_step → llm or agent → tool → llm.
5. Helpers degrade gracefully when OTEL is not initialised — they
   produce no spans but never crash (in-memory log path only).

All tests use ``InMemorySpanExporter`` with the existing module-scope
init pattern from ``test_otel_export.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.core.observability import tracing
from app.core.observability.agent_tracing import (
    OPENINFERENCE_SPAN_KIND,
    SpanKind,
    agent_span,
    llm_span,
    react_step_span,
    retriever_span,
    safe_attr_value,
    tool_span,
)


@pytest.fixture()
def exporter(otel_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    """Adapter for the local ``exporter`` name used by tests below —
    wraps the conftest-owned ``otel_exporter`` so both test modules
    share one OTEL setup and don't race on the global tracer provider."""
    return otel_exporter


# ---------------------------------------------------------------------------
# agent_span
# ---------------------------------------------------------------------------


def test_agent_span_sets_openinference_kind_and_name(
    exporter: InMemorySpanExporter,
) -> None:
    with agent_span(
        "policy_supervisor",
        agent_name="policy_supervisor_agent",
        tenant_id="t1",
        customer_id="c1",
        question="北京酒店报销上限？",
    ):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "agent.policy_supervisor"
    attrs = dict(s.attributes or {})
    assert attrs.get(OPENINFERENCE_SPAN_KIND) == SpanKind.AGENT
    assert attrs.get("agent.name") == "policy_supervisor_agent"
    assert attrs.get("tenant.id") == "t1"
    assert attrs.get("customer.id") == "c1"
    # input.value carries the question so trace UIs can show it as the span body
    assert "北京酒店" in str(attrs.get("input.value", ""))


def test_agent_span_optional_scope_fields_skipped_when_none(
    exporter: InMemorySpanExporter,
) -> None:
    with agent_span("policy_qa", agent_name="generic", question="Q"):
        pass
    attrs = dict(exporter.get_finished_spans()[0].attributes or {})
    assert "tenant.id" not in attrs
    assert "customer.id" not in attrs


# ---------------------------------------------------------------------------
# tool_span
# ---------------------------------------------------------------------------


def test_tool_span_sets_tool_attrs(exporter: InMemorySpanExporter) -> None:
    with tool_span(
        tool_name="policy_search",
        tool_input={"question": "Q", "tenant_id": "t1"},
    ) as span:
        span.set_attr("tool.status", "completed")
        span.set_attr("tool.latency_ms", 42)

    s = exporter.get_finished_spans()[0]
    attrs = dict(s.attributes or {})
    assert s.name == "tool.policy_search"
    assert attrs.get(OPENINFERENCE_SPAN_KIND) == SpanKind.TOOL
    assert attrs.get("tool.name") == "policy_search"
    # Pydantic-style JSON dump so trace UIs render the payload
    assert "question" in str(attrs.get("tool.parameters", ""))
    assert attrs.get("tool.status") == "completed"
    assert attrs.get("tool.latency_ms") == 42


def test_tool_span_handles_missing_input(exporter: InMemorySpanExporter) -> None:
    with tool_span(tool_name="noop_tool"):
        pass
    attrs = dict(exporter.get_finished_spans()[0].attributes or {})
    assert attrs.get("tool.name") == "noop_tool"
    # No parameters attr when no input was passed (avoid empty noise)
    assert "tool.parameters" not in attrs


# ---------------------------------------------------------------------------
# llm_span
# ---------------------------------------------------------------------------


def test_llm_span_sets_model_provider_and_kind(
    exporter: InMemorySpanExporter,
) -> None:
    with llm_span(
        purpose="react_plan",
        model_name="deepseek-v3-2-251201",
        provider="openai-compatible",
    ) as span:
        span.set_attr("llm.token_count.prompt", 1240)
        span.set_attr("llm.token_count.completion", 88)
        span.set_attr("llm.cost.usd", 0.00124)

    s = exporter.get_finished_spans()[0]
    attrs = dict(s.attributes or {})
    assert s.name == "llm.react_plan"
    assert attrs.get(OPENINFERENCE_SPAN_KIND) == SpanKind.LLM
    assert attrs.get("llm.model_name") == "deepseek-v3-2-251201"
    assert attrs.get("llm.provider") == "openai-compatible"
    assert attrs.get("llm.token_count.prompt") == 1240
    assert attrs.get("llm.token_count.completion") == 88
    assert attrs.get("llm.cost.usd") == pytest.approx(0.00124)


# ---------------------------------------------------------------------------
# retriever_span
# ---------------------------------------------------------------------------


def test_retriever_span_records_query_and_top_k(
    exporter: InMemorySpanExporter,
) -> None:
    # ``**extra`` keys land on the span verbatim — callers pick the
    # namespace explicitly to match dashboard conventions.
    with retriever_span(
        query="北京酒店报销上限",
        top_k=10,
        **{"retrieval.backend": "hybrid"},
    ) as span:
        span.set_attr("retrieval.documents.count", 3)

    s = exporter.get_finished_spans()[0]
    attrs = dict(s.attributes or {})
    assert s.name == "retriever"
    assert attrs.get(OPENINFERENCE_SPAN_KIND) == SpanKind.RETRIEVER
    assert "北京" in str(attrs.get("retrieval.query", ""))
    assert attrs.get("retrieval.top_k") == 10
    assert attrs.get("retrieval.backend") == "hybrid"
    assert attrs.get("retrieval.documents.count") == 3


# ---------------------------------------------------------------------------
# react_step_span — agent's plan / act / observe cycle
# ---------------------------------------------------------------------------


def test_react_step_span_records_cycle_and_plan(
    exporter: InMemorySpanExporter,
) -> None:
    with react_step_span(
        step=2,
        plan_action="call_tool",
        plan_tool="policy_search",
        fallback_used=False,
    ):
        pass
    s = exporter.get_finished_spans()[0]
    attrs = dict(s.attributes or {})
    assert s.name == "react.step.2"
    assert attrs.get(OPENINFERENCE_SPAN_KIND) == SpanKind.CHAIN
    assert attrs.get("react.step") == 2
    assert attrs.get("react.plan.action") == "call_tool"
    assert attrs.get("react.plan.tool") == "policy_search"
    assert attrs.get("react.plan.fallback_used") is False


def test_react_step_span_marks_fallback(exporter: InMemorySpanExporter) -> None:
    with react_step_span(step=1, plan_action="finalize", fallback_used=True):
        pass
    attrs = dict(exporter.get_finished_spans()[0].attributes or {})
    assert attrs.get("react.plan.fallback_used") is True


# ---------------------------------------------------------------------------
# Nested spans form the right trace tree
# ---------------------------------------------------------------------------


def test_agent_tool_llm_form_three_level_trace_tree(
    exporter: InMemorySpanExporter,
) -> None:
    """Real-world shape: agent → tool → llm. The trace UI must show this
    as a tree with three levels — otherwise the operator can't tell
    which LLM call belongs to which tool of which agent."""
    with agent_span("policy_supervisor", agent_name="policy_supervisor_agent", question="Q"):
        with tool_span(tool_name="policy_search"):
            with llm_span(purpose="answer", model_name="deepseek-v3", provider="openai-compatible"):
                pass

    spans = exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}
    agent = by_name["agent.policy_supervisor"]
    tool = by_name["tool.policy_search"]
    llm = by_name["llm.answer"]
    # llm child of tool, tool child of agent
    assert llm.parent.span_id == tool.context.span_id
    assert tool.parent.span_id == agent.context.span_id
    # All share the same trace_id
    assert llm.context.trace_id == tool.context.trace_id == agent.context.trace_id


def test_react_step_under_agent_under_react_planner(
    exporter: InMemorySpanExporter,
) -> None:
    """ReAct shape: agent → react_step → llm (planner) → … in same step."""
    with agent_span("policy_graph", agent_name="travel_policy_agent", question="Q"):
        with react_step_span(step=1, plan_action="call_tool", plan_tool="policy_search"):
            with llm_span(purpose="react_plan", model_name="m1", provider="openai-compatible"):
                pass
    spans = exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}
    assert by_name["llm.react_plan"].parent.span_id == by_name["react.step.1"].context.span_id
    assert by_name["react.step.1"].parent.span_id == by_name["agent.policy_graph"].context.span_id


# ---------------------------------------------------------------------------
# safe_attr_value — payload truncation
# ---------------------------------------------------------------------------


def test_safe_attr_value_truncates_long_strings() -> None:
    """OTLP attrs over ~4KB get rejected by some backends; truncate at 2KB
    to stay well under the limit."""
    huge = "x" * 10_000
    out = safe_attr_value(huge)
    assert isinstance(out, str)
    assert len(out) <= 2048


def test_safe_attr_value_serializes_dict_to_json() -> None:
    out = safe_attr_value({"question": "Q", "tenant_id": "t1"})
    assert isinstance(out, str)
    assert "question" in out
    assert "tenant_id" in out


def test_safe_attr_value_handles_none() -> None:
    assert safe_attr_value(None) == ""


def test_safe_attr_value_passes_through_primitives() -> None:
    """ints / floats / bools must NOT become strings — OTEL preserves
    typed attributes when the value is a native primitive."""
    assert safe_attr_value(42) == 42
    assert safe_attr_value(3.14) == 3.14
    assert safe_attr_value(True) is True


# ---------------------------------------------------------------------------
# No-op mode (when OTEL is not initialised)
# ---------------------------------------------------------------------------


def test_helpers_dont_crash_when_tracer_not_ready(monkeypatch) -> None:
    """The helpers must remain usable even when ``init_otel_tracer`` was
    never called — they just produce no exported spans. Patches the
    internal tracer lookup to return None instead of actually tearing
    down the session-scoped OTEL setup (would break sibling tests)."""
    monkeypatch.setattr(tracing, "_get_tracer_if_ready", lambda: None)
    with agent_span("x", agent_name="a", question="Q"):
        with tool_span(tool_name="t"):
            with llm_span(purpose="p", model_name="m", provider="openai-compatible"):
                pass
        with retriever_span(query="q", top_k=3):
            pass
        with react_step_span(step=0, plan_action="finalize"):
            pass
