import json

from sqlalchemy import text

from app.db.session import SessionLocal


def test_prompt_template_can_be_created_and_activated(client) -> None:
    create_response = client.post(
        "/api/prompts",
        json={
            "name": "默认政策问答 Prompt",
            "task_type": "policy_answer",
            "template": "你是差旅政策助手，请基于证据回答。",
        },
    )

    assert create_response.status_code == 201
    created_payload = create_response.json()
    assert created_payload["status"] == "draft"
    assert created_payload["version"] == 1

    first_template_id = created_payload["id"]

    second_response = client.post(
        "/api/prompts",
        json={
            "name": "默认政策问答 Prompt v2",
            "task_type": "policy_answer",
            "template": "你是差旅政策助手，请始终返回引用和置信度。",
        },
    )

    assert second_response.status_code == 201
    second_template_id = second_response.json()["id"]

    activate_first_response = client.post(f"/api/prompts/{first_template_id}/activate")
    assert activate_first_response.status_code == 200
    assert activate_first_response.json()["status"] == "active"

    activate_second_response = client.post(f"/api/prompts/{second_template_id}/activate")
    assert activate_second_response.status_code == 200
    assert activate_second_response.json()["status"] == "active"

    list_response = client.get("/api/prompts")
    assert list_response.status_code == 200

    prompts = list_response.json()["items"]
    prompt_map = {prompt["id"]: prompt for prompt in prompts}
    assert prompt_map[first_template_id]["status"] == "draft"
    assert prompt_map[second_template_id]["status"] == "active"


def test_policy_answer_persists_retrieval_trace_log(client, seeded_policy_chunks: None) -> None:
    response = client.post(
        "/api/chat/ask",
        json={
            "question": "Can I book business class?",
            "tenant_id": "t1",
            "customer_id": "c1",
        },
    )

    assert response.status_code == 200

    with SessionLocal() as session:
        row = (
            session.execute(
                text(
                    """
                SELECT question, model_name, prompt_name, citation_count, trace_json
                FROM rag_recall_log
                ORDER BY created_at DESC
                LIMIT 1
                """
                )
            )
            .mappings()
            .one()
        )

    assert row["question"] == "Can I book business class?"
    assert row["model_name"]
    assert row["prompt_name"]
    assert row["citation_count"] >= 1
    trace_payload = row["trace_json"]
    if isinstance(trace_payload, str):
        trace_payload = json.loads(trace_payload)
    assert trace_payload["selected_chunks"]
