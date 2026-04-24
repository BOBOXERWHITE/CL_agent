"""Per-tenant / model / agent daily token + cost aggregate (P5.2).

Why a separate aggregate table
------------------------------

The Phase 4 ``TaskRun`` + ``RagRecallLog`` rows carry per-request usage
but scanning those tables for "this tenant's spend last month" is
linear in request volume. An aggregate keyed by (tenant, day, model,
agent) gives the billing / dashboards O(tenants × days) scans instead.

The alternative — Prometheus histograms — works for ops dashboards but
can't attribute spend to a tenant, and Prometheus retention is usually
weeks (billing needs months).

Upsert pattern
--------------

Every request that uses tokens calls ``accumulate`` with the delta:

    (tenant_id, day, model_name, agent_name) → (+input, +output, +requests, +cost_cents)

PostgreSQL does this via ``INSERT ... ON CONFLICT DO UPDATE``. SQLite
(the test dialect) falls back to a SELECT + INSERT/UPDATE branch. Both
paths live in ``app.services.observability.token_sink`` so the model
file stays dialect-agnostic.

Cost ``null`` means "we recorded the tokens but didn't know the per-
token price at the time". Rates come from env (``COST_RATE_*``) — when
the rate for a model is not configured we deliberately leave the cost
field null rather than writing 0 (which would silently under-report).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TokenUsageDaily(Base):
    __tablename__ = "token_usage_daily"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "day",
            "model_name",
            "agent_name",
            name="uq_token_usage_daily_dim",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # "chat" / "ticket_router_agent" / "order_anomaly_agent" / "" (unknown)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Cost in 1/100 cent (``micros`` would be nicer but overkill for
    # per-tenant billing — 10-digit int is enough for 10^8 USD).
    cost_usd_cents: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
