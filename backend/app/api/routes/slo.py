"""``GET /api/health/slo`` — rolling-window SLO snapshot (P7.4).

Reads ``runtime_log`` for the last N minutes and derives:

- ``request_count`` — total requests observed in window
- ``p50_latency_ms`` / ``p95_latency_ms`` — latency percentiles
- ``error_rate`` — fraction of requests with status_code >= 500
- ``cache_hit_rate`` — best-effort from Prometheus counter (null if
  the metric family doesn't exist yet)
- ``active_chat_sessions`` — rough activity proxy: distinct session_id
  seen in the window

Percentiles are computed in Python rather than in SQL because SQLite
(the default dev/test backend) doesn't have ``percentile_cont``. For
PG we'd ideally push this down; the list has an O(N) upper bound
capped by the rolling window so the memory hit is bounded.

``window_minutes`` is configurable via query param (default 5, max 60).

Auth: admin / operator — dashboards shouldn't leak latency distribution
to end users.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_request_context
from app.core.security import AuthContext, require_roles
from app.db.models.runtime_log import RuntimeLog
from app.db.session import get_session

router = APIRouter(prefix="/api/health", tags=["health"])


class SloSnapshot(BaseModel):
    window_minutes: int
    request_count: int
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    error_rate: float | None
    cache_hit_rate: float | None
    active_chat_sessions: int
    updated_at: datetime


def _percentile(values: list[int], fraction: float) -> int | None:
    """Inclusive linear-interpolation percentile; returns None for an
    empty list so the caller can surface "no data" cleanly."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * fraction
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return int(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _cache_hit_rate_from_prometheus() -> float | None:
    """Pull cache hit/miss counters from Prometheus registry.

    Returns None when the metric family isn't registered (e.g. brand-
    new process) — lets the UI say "no cache data yet" instead of 0.
    """
    try:
        from app.core.metrics import (  # type: ignore[attr-defined]
            rag_cache_hits_total,
            rag_cache_misses_total,
        )
    except ImportError:
        return None
    try:
        hits = sum(
            sample.value
            for metric in rag_cache_hits_total.collect()
            for sample in metric.samples
            if sample.name.endswith("_total")
        )
        misses = sum(
            sample.value
            for metric in rag_cache_misses_total.collect()
            for sample in metric.samples
            if sample.name.endswith("_total")
        )
    except Exception:
        return None
    total = hits + misses
    if total <= 0:
        return None
    return round(hits / total, 4)


@router.get("/slo", response_model=SloSnapshot)
def get_slo_snapshot(
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
    window_minutes: int = Query(default=5, ge=1, le=60),
) -> SloSnapshot:
    """Snapshot of the current tenant's runtime health."""
    request.state.request_id = context.request_id
    request.state.tenant_id = context.tenant_id

    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=window_minutes)

    base_filter = [
        RuntimeLog.created_at >= cutoff,
    ]
    if context.tenant_id and context.tenant_id not in ("default-tenant", ""):
        # Tenant scoping: non-default tenants see only their own rows.
        base_filter.append(RuntimeLog.tenant_id == context.tenant_id)

    latencies = [
        int(row[0] or 0)
        for row in session.execute(select(RuntimeLog.latency_ms).where(*base_filter)).all()
    ]
    total = len(latencies)

    error_count = int(
        session.execute(
            select(func.count())
            .select_from(RuntimeLog)
            .where(*base_filter)
            .where(RuntimeLog.status_code >= 500)
        ).scalar_one()
    )
    error_rate = round(error_count / total, 4) if total else None

    active_sessions = int(
        session.execute(
            select(func.count(distinct(RuntimeLog.session_id))).where(
                *base_filter,
                RuntimeLog.session_id.isnot(None),
            )
        ).scalar_one()
    )

    return SloSnapshot(
        window_minutes=window_minutes,
        request_count=total,
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        error_rate=error_rate,
        cache_hit_rate=_cache_hit_rate_from_prometheus(),
        active_chat_sessions=active_sessions,
        updated_at=now,
    )
