from tests.conftest import DOCX_CONTENT_TYPE


def test_upload_endpoint_returns_job_id(client, docx_file: bytes) -> None:
    response = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 202

    payload = response.json()
    assert payload["job_id"]
    assert payload["document_id"]
    assert payload["status"] == "completed"

    jobs_response = client.get("/api/knowledge/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["items"][0]["chunk_count"] > 0
