from __future__ import annotations

from pydantic import BaseModel

from app.services.agents.policy_domain import choose_policy_specialist
from app.services.agents.tool_gateway import run_guarded_tool
from app.services.agents.tool_registry import Tool, ToolRegistry
from app.services.agents.tool_runner import ToolRunner


def test_policy_domain_router_prefers_hotel_specialist() -> None:
    decision = choose_policy_specialist("L2 员工在北京住 760 元/晚，含早且发票分住宿费和餐饮费")
    assert decision.domain == "hotel"
    assert decision.specialist == "hotel_policy_agent"
    assert decision.confidence > 0.8


class _HighRiskInput(BaseModel):
    value: str


class _HighRiskOutput(BaseModel):
    echoed: str


class _HighRiskTool(Tool):
    name = "high_risk_echo"
    description = "echoes a value but requires approval"
    input_model = _HighRiskInput
    output_model = _HighRiskOutput
    risk_level = "high"
    requires_approval = True
    idempotency_scope = "thread"

    def invoke(self, payload: BaseModel) -> BaseModel:
        assert isinstance(payload, _HighRiskInput)
        return _HighRiskOutput(echoed=payload.value)


def test_tool_gateway_interrupts_high_risk_tool(monkeypatch) -> None:
    import app.services.agents.tool_gateway as gateway

    registry = ToolRegistry()
    registry.register(_HighRiskTool())
    runner = ToolRunner(registry)
    monkeypatch.setattr(gateway, "get_default_registry", lambda: registry)
    monkeypatch.setattr(gateway, "get_default_tool_runner", lambda: runner)

    result = run_guarded_tool("high_risk_echo", {"value": "secret"}, thread_id="thread-1")
    assert result.interrupted is True
    assert result.status == "interrupted"
    assert result.guardrail_events[0]["decision"] == "interrupt"
