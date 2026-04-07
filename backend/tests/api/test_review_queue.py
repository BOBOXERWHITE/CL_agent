from __future__ import annotations


def test_low_confidence_agent_result_creates_review_case(client) -> None:
    response = client.post(
        "/api/reviews/ingest",
        json={
            "source": "agent",
            "confidence": 0.32,
            "tenant_id": "t1",
            "customer_id": "c1",
            "reason": "工单分流置信度过低",
            "payload": {"question": "这张单据为什么被拦截？"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "open"
    assert payload["source"] == "agent"
    assert payload["suggested_action"] == "转人工复核"


def test_blocked_agent_run_is_written_to_review_queue(client) -> None:
    response = client.post(
        "/api/agents/runs",
        json={
            "question": "这张北京酒店报销单为什么还在排队？",
            "tenant_id": "t1",
            "customer_id": "c1",
            "ticket": {
                "ticket_id": "ticket-101",
                "expense_type": "hotel",
                "city": "北京",
                "amount": 2200,
                "status": "pending_review",
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["output"]["rule_result"]["decision"] == "blocked"

    queue_response = client.get("/api/reviews/queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["items"]
    assert queue_payload["items"][0]["source"] == "agent"
    assert queue_payload["items"][0]["rule_result"]["decision"] == "blocked"
