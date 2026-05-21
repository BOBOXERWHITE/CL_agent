"""P7 Phase B: tests for the LLM-driven ReAct planner.

The planner is the brain replacement for ``policy_graph._plan_node``'s
hardcoded "if no obs, call policy_search; else finalize" decision.
When ``settings.agent_react_llm_enabled`` is True it asks the LLM at
each step which tool to call (or whether to finalize), enabling true
multi-tool / multi-cycle ReAct. When False (default), or whenever the
LLM call fails, it falls back to the legacy hardcoded behaviour
bit-for-bit.

Invariants under test:

1. **Off by default**: with the flag False, no HTTP call happens and
   the verdict matches the legacy hardcoded plan. This keeps every
   existing policy_graph test passing without modification.
2. **Fail-soft**: HTTP error / non-JSON / unknown tool / missing
   action → fallback verdict with ``fallback_used=True`` so the eval
   layer can surface "planner gave up N times this run" instead of
   crashing the whole question.
3. **Plan output is sanitized**: ``thought`` is length-clamped (to
   keep DB rows bounded) and unknown tool names are rejected against
   the allow-list (no LLM hallucination of fake tool names).
4. **Multi-cycle**: when the planner has past observations + thoughts
   in scratchpad, the prompt includes them so the LLM can decide
   "enough evidence" vs "call another tool".
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.services.agents.react_planner import (
    PlanResponse,
    plan_next_action,
)


@pytest.fixture
def planner_settings(monkeypatch) -> Settings:
    """Force AGENT_REACT_LLM_ENABLED with a fake openai-compatible gateway."""
    settings = get_settings()
    overridden = replace(
        settings,
        agent_react_llm_enabled=True,
        llm_provider="openai-compatible",
        llm_api_base_url="https://planner.example.test/v1",
        llm_api_key="fake-key",
        llm_model_name="planner-test-model",
    )
    monkeypatch.setattr("app.services.agents.react_planner.get_settings", lambda: overridden)
    return overridden


def _mock_transport(payload: dict[str, object]) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _mock_transport_status(status_code: int, body: str = "") -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body.encode("utf-8"))

    return httpx.MockTransport(handler)


_TOOL_CATALOG = [
    {
        "name": "policy_search",
        "description": "Search the policy knowledge base for relevant evidence.",
    },
    {
        "name": "rule_lookup",
        "description": "Look up a specific rule by id.",
    },
]


def test_disabled_returns_hardcoded_call_tool_with_no_observations(
    monkeypatch,
) -> None:
    """Flag off + scratchpad empty → fall back to "call policy_search"."""
    settings = get_settings()
    monkeypatch.setattr(
        "app.services.agents.react_planner.get_settings",
        lambda: replace(settings, agent_react_llm_enabled=False),
    )

    def fail(*_a, **_kw):  # pragma: no cover - defensive
        raise AssertionError("must not open httpx client when disabled")

    monkeypatch.setattr("httpx.Client", fail)

    plan = plan_next_action(
        question="北京酒店报销上限？",
        observations=[],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=0,
    )
    assert plan.action == "call_tool"
    assert plan.tool == "policy_search"
    assert plan.fallback_used is True


def test_disabled_returns_hardcoded_finalize_with_observations(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        "app.services.agents.react_planner.get_settings",
        lambda: replace(settings, agent_react_llm_enabled=False),
    )

    plan = plan_next_action(
        question="Q",
        observations=[{"tool": "policy_search", "output": {"answer": "OK"}}],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=1,
    )
    assert plan.action == "finalize"
    assert plan.tool is None
    assert plan.fallback_used is True


def test_enabled_parses_llm_call_tool_plan(planner_settings: Settings) -> None:
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "thought": "Need to fetch the room-rate matrix first.",
                                "action": "call_tool",
                                "tool": "policy_search",
                                "tool_args": {"focus": "room_rate"},
                            }
                        )
                    }
                }
            ]
        }
    )
    plan = plan_next_action(
        question="L2 员工北京酒店上限",
        observations=[],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=0,
        http_client=httpx.Client(transport=transport),
    )
    assert plan.action == "call_tool"
    assert plan.tool == "policy_search"
    assert plan.tool_args == {"focus": "room_rate"}
    assert plan.fallback_used is False
    assert "room-rate" in plan.thought


def test_enabled_parses_llm_finalize_plan(planner_settings: Settings) -> None:
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "thought": "Evidence collected; answer is clear.",
                                "action": "finalize",
                            }
                        )
                    }
                }
            ]
        }
    )
    plan = plan_next_action(
        question="Q",
        observations=[{"tool": "policy_search", "output": {"answer": "700"}}],
        thoughts=["I should look up the rate matrix"],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=1,
        http_client=httpx.Client(transport=transport),
    )
    assert plan.action == "finalize"
    assert plan.tool is None
    assert plan.fallback_used is False


def test_enabled_rejects_unknown_tool_via_fallback(planner_settings: Settings) -> None:
    """If the LLM hallucinates a tool not in the allow-list, we must NOT
    propagate it (would crash the tool runner). Fall back instead."""
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "thought": "Made up tool name.",
                                "action": "call_tool",
                                "tool": "magic_tool_that_does_not_exist",
                            }
                        )
                    }
                }
            ]
        }
    )
    plan = plan_next_action(
        question="Q",
        observations=[],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=0,
        http_client=httpx.Client(transport=transport),
    )
    assert plan.fallback_used is True
    # Hardcoded fallback for no-obs case → call_tool policy_search
    assert plan.action == "call_tool"
    assert plan.tool == "policy_search"


def test_enabled_falls_back_on_http_error(planner_settings: Settings) -> None:
    transport = _mock_transport_status(500, "boom")
    plan = plan_next_action(
        question="Q",
        observations=[],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=0,
        http_client=httpx.Client(transport=transport),
    )
    assert plan.fallback_used is True


def test_enabled_falls_back_on_non_json_content(planner_settings: Settings) -> None:
    transport = _mock_transport({"choices": [{"message": {"content": "not json {{{"}}]})
    plan = plan_next_action(
        question="Q",
        observations=[],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=0,
        http_client=httpx.Client(transport=transport),
    )
    assert plan.fallback_used is True


def test_enabled_falls_back_on_missing_action_field(planner_settings: Settings) -> None:
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"thought": "no action", "tool": "policy_search"})
                    }
                }
            ]
        }
    )
    plan = plan_next_action(
        question="Q",
        observations=[],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=0,
        http_client=httpx.Client(transport=transport),
    )
    assert plan.fallback_used is True


def test_enabled_clamps_thought_length(planner_settings: Settings) -> None:
    long_thought = "x" * 5000
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "thought": long_thought,
                                "action": "finalize",
                            }
                        )
                    }
                }
            ]
        }
    )
    plan = plan_next_action(
        question="Q",
        observations=[{"tool": "policy_search", "output": {"answer": "OK"}}],
        thoughts=[],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=1,
        http_client=httpx.Client(transport=transport),
    )
    assert plan.action == "finalize"
    assert len(plan.thought) <= 1024  # clamp guard


def test_enabled_prompt_carries_past_observations_for_multi_cycle(
    planner_settings: Settings,
) -> None:
    """When called mid-loop, the request body must include past
    observations + thoughts so the LLM can decide 'enough evidence'."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"thought": "have enough", "action": "finalize"})
                        }
                    }
                ]
            },
        )

    plan = plan_next_action(
        question="Q",
        observations=[
            {"tool": "policy_search", "output": {"answer": "Beijing cap 700"}},
            {"tool": "rule_lookup", "output": {"rule": "R-12"}},
        ],
        thoughts=["First I checked policy", "Now I should check the rule"],
        available_tools=_TOOL_CATALOG,
        max_steps=8,
        current_step=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert plan.action == "finalize"
    body = str(captured["body"])
    assert "Beijing cap 700" in body
    assert "R-12" in body
    assert "First I checked policy" in body


def test_plan_response_is_immutable() -> None:
    plan = PlanResponse(
        action="finalize",
        tool=None,
        tool_args={},
        thought="t",
        fallback_used=False,
    )
    with pytest.raises((AttributeError, TypeError)):
        plan.action = "call_tool"  # type: ignore[misc]
