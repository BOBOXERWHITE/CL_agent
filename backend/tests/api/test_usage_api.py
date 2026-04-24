"""Route-level tests for ``GET /api/usage`` (P5.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.db.models.token_usage import TokenUsageDaily
from app.db.session import SessionLocal


def _seed(
    *,
    tenant_id: str = "default-tenant",
    day: date | None = None,
    model_name: str = "gpt-4",
    agent_name: str = "chat",
    input_tokens: int = 100,
    output_tokens: int = 50,
    requests: int = 1,
    cost_usd_cents: int | None = None,
) -> None:
    with SessionLocal() as session:
        session.add(
            TokenUsageDaily(
                tenant_id=tenant_id,
                day=day or datetime.now(UTC).date(),
                model_name=model_name,
                agent_name=agent_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                requests=requests,
                cost_usd_cents=cost_usd_cents,
            )
        )
        session.commit()


def test_usage_default_group_by_model(client: TestClient) -> None:
    _seed(model_name="gpt-4", input_tokens=100, output_tokens=50)
    _seed(model_name="gpt-4", input_tokens=200, output_tokens=100, agent_name="policy")
    _seed(model_name="claude-3", input_tokens=50, output_tokens=20)

    resp = client.get("/api/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    by_model = {item["model_name"]: item for item in body["items"]}
    # gpt-4 sums across both agents.
    assert by_model["gpt-4"]["input_tokens"] == 300
    assert by_model["gpt-4"]["output_tokens"] == 150
    assert by_model["gpt-4"]["requests"] == 2
    assert by_model["claude-3"]["input_tokens"] == 50


def test_usage_group_by_agent(client: TestClient) -> None:
    _seed(agent_name="chat", input_tokens=10)
    _seed(agent_name="policy", input_tokens=20)
    _seed(agent_name="policy", input_tokens=30, model_name="claude-3")

    resp = client.get("/api/usage", params={"group_by": "agent"})
    assert resp.status_code == 200
    body = resp.json()
    by_agent = {item["agent_name"]: item for item in body["items"]}
    assert by_agent["chat"]["input_tokens"] == 10
    assert by_agent["policy"]["input_tokens"] == 50  # 20 + 30


def test_usage_group_by_day_returns_time_series(client: TestClient) -> None:
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    _seed(day=yesterday, input_tokens=100)
    _seed(day=today, input_tokens=200)

    resp = client.get("/api/usage", params={"group_by": "day"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2


def test_usage_summary_aggregates_totals(client: TestClient) -> None:
    _seed(input_tokens=100, output_tokens=50, cost_usd_cents=3)
    _seed(input_tokens=200, output_tokens=100, cost_usd_cents=6, agent_name="policy")

    resp = client.get("/api/usage")
    body = resp.json()
    assert body["summary"]["total_input_tokens"] == 300
    assert body["summary"]["total_output_tokens"] == 150
    assert body["summary"]["total_requests"] == 2
    assert body["summary"]["total_cost_usd_cents"] == 9


def test_usage_cost_null_when_all_buckets_null(client: TestClient) -> None:
    """If no bucket carries cost, the summary cost must be null (not 0)
    to make "cost unknown" distinguishable from "$0 cost" in the UI."""
    _seed(cost_usd_cents=None)
    _seed(cost_usd_cents=None, agent_name="policy")

    resp = client.get("/api/usage")
    body = resp.json()
    assert body["summary"]["total_cost_usd_cents"] is None


def test_usage_date_filter_narrows_window(client: TestClient) -> None:
    today = datetime.now(UTC).date()
    long_ago = today - timedelta(days=60)
    _seed(day=long_ago, input_tokens=500)
    _seed(day=today, input_tokens=100)

    resp = client.get(
        "/api/usage",
        params={"from": (today - timedelta(days=7)).isoformat()},
    )
    body = resp.json()
    assert body["summary"]["total_input_tokens"] == 100  # only today's row


def test_usage_tenant_isolation(client: TestClient) -> None:
    _seed(tenant_id="default-tenant", input_tokens=100)
    _seed(tenant_id="other-tenant", input_tokens=999)

    resp = client.get("/api/usage")
    body = resp.json()
    assert body["summary"]["total_input_tokens"] == 100


def test_usage_group_by_none_returns_raw_rows(client: TestClient) -> None:
    today = datetime.now(UTC).date()
    _seed(day=today, model_name="gpt-4", input_tokens=10)
    _seed(day=today - timedelta(days=1), model_name="gpt-4", input_tokens=20)

    resp = client.get("/api/usage", params={"group_by": "none"})
    body = resp.json()
    assert len(body["items"]) == 2
    # Both raw rows carry a day.
    assert all(item["day"] is not None for item in body["items"])


def test_usage_reviewer_forbidden(client: TestClient) -> None:
    """Usage data = spend profile; reviewer role must not see it."""
    _seed(input_tokens=100)

    resp = client.get(
        "/api/usage",
        headers={"Authorization": "Bearer reviewer-token"},
    )
    assert resp.status_code == 403
