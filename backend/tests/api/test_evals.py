def test_eval_run_endpoint_returns_metrics(client, seeded_multilingual_policy_chunks: None) -> None:
    response = client.post("/api/evals/runs", json={"dataset_name": "zh-policy-smoke"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["dataset_name"] == "zh-policy-smoke"
    assert payload["question_count"] >= 1
    assert payload["metrics"]["answer_correctness"] >= 0
    assert len(payload["details"]) == payload["question_count"]
    assert "question" in payload["details"][0]
