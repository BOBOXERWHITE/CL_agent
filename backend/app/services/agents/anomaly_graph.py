from __future__ import annotations

from app.services.agents.nodes import append_timeline_step
from app.services.agents.state import AgentExecutionResult, TimelineStep


def execute_anomaly_graph(
    *,
    question: str,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    timeline = list(base_timeline)
    append_timeline_step(
        timeline,
        node_name="order_anomaly_triage",
        status="completed",
        detail=f"已识别异常订单语义：{question}",
    )
    append_timeline_step(
        timeline,
        node_name="human_review_checkpoint",
        status="required",
        detail="异常订单需转人工核查。",
    )
    return AgentExecutionResult(
        agent_name="order_anomaly_agent",
        route_name=route_name,
        status="completed",
        confidence=0.74,
        requires_human_review=True,
        output={
            "queue_name": "ops-review",
            "reason": "异常订单类问题默认进入运营人工复核。",
        },
        timeline=timeline,
        tool_calls=[],
    )
