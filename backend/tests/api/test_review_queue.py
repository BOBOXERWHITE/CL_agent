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
    assert queue_payload["items"][0]["agent_run_id"] == payload["id"]
    assert queue_payload["items"][0]["thread_id"] == payload["thread_id"]
    assert queue_payload["items"][0]["pending_interrupt"]["queue_name"] == "finance-review"
    assert (
        queue_payload["items"][0]["latest_checkpoint"]["checkpoint_type"] == "engine_adapter_state"
    )
    assert queue_payload["items"][0]["latest_checkpoint"]["status"] == "paused"
    trace_events = queue_payload["items"][0]["trace_events"]
    assert any(
        event["category"] == "interrupt"
        and event["name"] == "human_review"
        and event["metadata"]["queue_name"] == "finance-review"
        for event in trace_events
    )
    assert any(
        event["category"] == "review"
        and event["name"] == "review_case"
        and event["status"] == "open"
        for event in trace_events
    )
