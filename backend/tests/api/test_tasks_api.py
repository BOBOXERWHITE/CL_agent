"""Route-level tests for P4.5: ``/api/tasks`` list / detail / cancel.

We seed ``task_run`` rows directly (not via ``submit_ingestion``) so the
tests focus on the API surface without pulling in the ingestion
pipeline. The sink helpers from P4.4 are already covered separately.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models.task_run import TaskRun
from app.db.session import SessionLocal


def _seed_task(
    *,
    task_id: str | None = None,
    tenant_id: str = "default-tenant",
    task_name: str = "knowledge.ingest_document",
    status: str = "pending",
    idempotency_key: str | None = None,
    summary: str = "",
    created_at: datetime | None = None,
) -> str:
    task_id = task_id or str(uuid4())
    with SessionLocal() as session:
        session.add(
            TaskRun(
                id=task_id,
                tenant_id=tenant_id,
                user_id="alice",
                task_name=task_name,
                status=status,
                idempotency_key=idempotency_key,
                input_json={"document_id": "d1"},
                retries=0,
                trace_id="req-1",
                summary=summary or f"Ingest doc via {task_name}",
                created_at=created_at or datetime.now(UTC),
                updated_at=created_at or datetime.now(UTC),
            )
        )
        session.commit()
    return task_id


def test_list_tasks_returns_current_tenant_rows(client: TestClient) -> None:
    _seed_task(tenant_id="default-tenant", status="running", summary="run 1")
    _seed_task(tenant_id="default-tenant", status="succeeded", summary="run 2")
    # Other tenant — must not leak into the response.
    _seed_task(tenant_id="other-tenant", status="running", summary="other")

    resp = client.get("/api/tasks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert {item["summary"] for item in body["items"]} == {"run 1", "run 2"}


def test_list_tasks_filters_by_status(client: TestClient) -> None:
    _seed_task(status="running")
    _seed_task(status="succeeded")
    _seed_task(status="failed")

    resp = client.get("/api/tasks", params={"status": "failed"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"


def test_list_tasks_paginates_newest_first(client: TestClient) -> None:
    base = datetime.now(UTC)
    _seed_task(summary="oldest", created_at=base - timedelta(minutes=5))
    _seed_task(summary="middle", created_at=base - timedelta(minutes=3))
    _seed_task(summary="newest", created_at=base - timedelta(minutes=1))

    # limit=2 → should return the two newest in order.
    resp = client.get("/api/tasks", params={"limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    summaries = [item["summary"] for item in body["items"]]
    assert summaries == ["newest", "middle"]
    assert body["total"] == 3


def test_get_task_returns_detail(client: TestClient) -> None:
    task_id = _seed_task(status="succeeded", summary="detail-target")

    resp = client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == task_id
    assert body["status"] == "succeeded"
    assert body["summary"] == "detail-target"


def test_get_task_unknown_returns_404(client: TestClient) -> None:
    resp = client.get("/api/tasks/does-not-exist")
    assert resp.status_code == 404


def test_cancel_running_task_marks_canceled(client: TestClient) -> None:
    task_id = _seed_task(status="running")

    resp = client.post(
        f"/api/tasks/{task_id}/cancel",
        json={"note": "用户取消"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transitioned"] is True
    assert body["task"]["status"] == "canceled"
    assert body["task"]["error"] == {
        "reason": "canceled_by_reviewer",
        "note": "用户取消",
    }


def test_cancel_already_canceled_is_idempotent(client: TestClient) -> None:
    task_id = _seed_task(status="running")
    client.post(f"/api/tasks/{task_id}/cancel", json={"note": "first"})

    # Second cancel: same 200 status, transitioned=False, state unchanged.
    resp = client.post(f"/api/tasks/{task_id}/cancel", json={"note": "second"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["transitioned"] is False
    assert body["task"]["status"] == "canceled"
    # Note from the first call wins — the idempotent re-call must not
    # overwrite the original reason.
    assert body["task"]["error"]["note"] == "first"


def test_cancel_succeeded_task_returns_409(client: TestClient) -> None:
    task_id = _seed_task(status="succeeded")

    resp = client.post(f"/api/tasks/{task_id}/cancel", json={"note": "too late"})
    assert resp.status_code == 409


def test_cancel_failed_task_returns_409(client: TestClient) -> None:
    task_id = _seed_task(status="failed")

    resp = client.post(f"/api/tasks/{task_id}/cancel", json={"note": ""})
    assert resp.status_code == 409


def test_cancel_unknown_task_returns_404(client: TestClient) -> None:
    resp = client.post("/api/tasks/missing/cancel", json={"note": ""})
    assert resp.status_code == 404


def test_cancel_requires_admin_or_operator(client: TestClient) -> None:
    """Reviewer role can list / read but MUST NOT cancel — cancel leaves
    side effects in object storage that ordinary reviewers can't clean.
    """
    task_id = _seed_task(status="running")
    resp = client.post(
        f"/api/tasks/{task_id}/cancel",
        headers={"Authorization": "Bearer reviewer-token"},
        json={"note": ""},
    )
    assert resp.status_code == 403


def test_list_tasks_reviewer_allowed(client: TestClient) -> None:
    _seed_task(status="running")
    resp = client.get(
        "/api/tasks",
        headers={"Authorization": "Bearer reviewer-token"},
    )
    assert resp.status_code == 200
