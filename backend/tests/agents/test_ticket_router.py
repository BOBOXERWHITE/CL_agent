from __future__ import annotations

from app.services.agents.ticket_router_graph import run_ticket_router


def test_ticket_router_agent_returns_queue_and_reason() -> None:
    result = run_ticket_router(
        {
            "ticket_id": "ticket-001",
            "expense_type": "hotel",
            "city": "北京",
            "amount": 1200,
            "status": "pending_review",
        }
    )

    assert result.queue_name == "finance-review"
    assert "超出酒店标准" in result.reason
    assert result.tool_calls
    assert result.tool_calls[0].tool_name == "ticket_queue_lookup"


def test_agent_run_endpoint_returns_timeline_and_tool_calls(
    client,
    seeded_multilingual_policy_chunks: None,
) -> None:
    response = client.post(
        "/api/agents/runs",
        json={
            "question": "这张北京酒店报销单为什么还在排队？",
            "tenant_id": "t1",
            "customer_id": "c1",
            "ticket": {
                "ticket_id": "ticket-002",
                "expense_type": "hotel",
                "city": "北京",
                "amount": 1200,
                "status": "pending_review",
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["agent_name"] == "ticket_router_agent"
    assert payload["status"] == "needs_review"
    assert payload["tool_calls"]
    assert payload["timeline"]
    assert payload["timeline"][0]["node_name"] == "router"
    assert payload["output"]["queue_name"] == "finance-review"
    assert payload["output"]["rule_result"]["decision"] == "blocked"
    assert payload["output"]["review_case_id"]
