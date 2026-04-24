"""``GET /api/usage`` — per-tenant token / cost aggregate (P5.2).

Shape
-----

``GET /api/usage?from=2026-04-01&to=2026-04-30&group_by=model``

- ``group_by=model`` (default): one bucket per (model).
- ``group_by=agent``: one bucket per (agent).
- ``group_by=day``: one bucket per day (time series).
- ``group_by=none`` (or omitted + ``detailed=true``): raw rows.

The ``items`` list carries per-bucket sums; the ``summary`` block
carries the cross-bucket totals so the dashboard doesn't have to
re-add on the client.

``from`` / ``to`` default to last 30 days. Both are inclusive dates in
UTC. Missing ``to`` = today.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.core.security import AuthContext, require_roles
from app.db.models.token_usage import TokenUsageDaily
from app.db.session import get_session
from app.schemas.token_usage import (
    TokenUsageBucket,
    TokenUsageResponse,
    TokenUsageSummary,
)

router = APIRouter(prefix="/api/usage", tags=["usage"])


_ALLOWED_GROUPS = frozenset({"model", "agent", "day", "none"})


def _sum_nullable(values: list[int | None]) -> int | None:
    """Sum ints treating None as "missing"; return None if every entry
    was None (so the client can tell apart "no cost data" from "0 cost")."""
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return sum(filtered)


@router.get("", response_model=TokenUsageResponse)
def get_usage(
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
    group_by: str = Query(default="model"),
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
) -> TokenUsageResponse:
    """Aggregate tokens + cost scoped to the caller's tenant.

    Admin / operator only — usage data is sensitive (spend profile).
    Reviewer role intentionally excluded.
    """
    request.state.request_id = context.request_id
    request.state.tenant_id = context.tenant_id

    group = group_by.lower() if group_by else "model"
    if group not in _ALLOWED_GROUPS:
        group = "model"

    today = datetime.now(UTC).date()
    start = datetime.fromisoformat(from_date).date() if from_date else today - timedelta(days=30)
    end = datetime.fromisoformat(to_date).date() if to_date else today

    base_filter = [
        TokenUsageDaily.tenant_id == context.tenant_id,
        TokenUsageDaily.day >= start,
        TokenUsageDaily.day <= end,
    ]

    if group == "none":
        query = (
            select(TokenUsageDaily)
            .where(*base_filter)
            .order_by(
                TokenUsageDaily.day.desc(),
                TokenUsageDaily.model_name,
                TokenUsageDaily.agent_name,
            )
        )
        rows = list(session.execute(query).scalars())
        items = [
            TokenUsageBucket(
                tenant_id=row.tenant_id,
                day=row.day,
                model_name=row.model_name,
                agent_name=row.agent_name,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                requests=row.requests,
                cost_usd_cents=row.cost_usd_cents,
            )
            for row in rows
        ]
    else:
        # Group by exactly one dimension (model / agent / day). We keep
        # the branches explicit rather than a clever dict-of-columns so
        # column position + field extraction stay obviously correct.
        if group == "model":
            key_col = TokenUsageDaily.model_name
        elif group == "agent":
            key_col = TokenUsageDaily.agent_name
        else:
            key_col = TokenUsageDaily.day
        query = (
            select(
                key_col.label("group_key"),
                func.sum(TokenUsageDaily.input_tokens).label("input"),
                func.sum(TokenUsageDaily.output_tokens).label("output"),
                func.sum(TokenUsageDaily.requests).label("requests"),
                func.sum(TokenUsageDaily.cost_usd_cents).label("cost"),
            )
            .where(*base_filter)
            .group_by(key_col)
        )
        grouped = list(session.execute(query).all())
        items = []
        for key_val, input_sum, output_sum, req_sum, cost_sum in grouped:
            items.append(
                TokenUsageBucket(
                    tenant_id=context.tenant_id,
                    day=key_val if group == "day" else None,
                    model_name=str(key_val) if group == "model" else "",
                    agent_name=str(key_val) if group == "agent" else "",
                    input_tokens=int(input_sum or 0),
                    output_tokens=int(output_sum or 0),
                    requests=int(req_sum or 0),
                    cost_usd_cents=int(cost_sum) if cost_sum is not None else None,
                )
            )

    summary = TokenUsageSummary(
        total_input_tokens=sum(i.input_tokens for i in items),
        total_output_tokens=sum(i.output_tokens for i in items),
        total_requests=sum(i.requests for i in items),
        total_cost_usd_cents=_sum_nullable([i.cost_usd_cents for i in items]),
    )
    return TokenUsageResponse(items=items, summary=summary)
