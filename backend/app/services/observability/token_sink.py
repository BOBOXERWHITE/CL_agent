"""Token + cost aggregation sink (P5.2 / P5-patch-B atomic).

Exposes ``accumulate(...)`` which upserts a ``token_usage_daily`` row
for the given dimension tuple. Two dialect-aware strategies (both
atomic — P5-patch-B fixed the original SELECT + INSERT/UPDATE race):

- **PostgreSQL**: ``INSERT ... ON CONFLICT DO UPDATE`` via the
  ``postgresql.insert`` dialect helper. One round-trip, single
  statement; two concurrent workers on the same ``(tenant, day, model,
  agent)`` key merge into the same row instead of one of them blowing
  up on the unique constraint.
- **SQLite** (tests) / other: ``INSERT`` first, catch
  ``IntegrityError``, fall back to ``UPDATE`` using the unique tuple
  as the WHERE clause. The retry is bounded (one round) so a permanent
  constraint violation still surfaces.

Cost rates are read from env vars at call time:

    COST_RATE_{MODEL}_INPUT_PER_1K_CENTS
    COST_RATE_{MODEL}_OUTPUT_PER_1K_CENTS

Model name is upper-cased and ``/``, ``-``, ``.`` replaced with ``_``
for env-var safety. Missing config → cost kept null (we'd rather
under-report cost than fabricate).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.token_usage import TokenUsageDaily

_log = logging.getLogger(__name__)

_MODEL_NAME_SANITIZE = re.compile(r"[^A-Z0-9]+")


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _env_rate(model_name: str, direction: str) -> float | None:
    """Return the per-1k-tokens cost (in cents, fractional allowed) or None."""
    if not model_name:
        return None
    key_model = _MODEL_NAME_SANITIZE.sub("_", model_name.upper()).strip("_")
    env_key = f"COST_RATE_{key_model}_{direction.upper()}_PER_1K_CENTS"
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        _log.warning("token_cost_rate_invalid", extra={"env_key": env_key, "raw": raw})
        return None


def _compute_cost_cents(model_name: str, input_tokens: int, output_tokens: int) -> int | None:
    """Return cost in integer cents, or None when no rate is configured."""
    in_rate = _env_rate(model_name, "input")
    out_rate = _env_rate(model_name, "output")
    if in_rate is None and out_rate is None:
        return None
    cost = 0.0
    if in_rate is not None:
        cost += (input_tokens / 1000.0) * in_rate
    if out_rate is not None:
        cost += (output_tokens / 1000.0) * out_rate
    # Round half-up to an integer cent; cost below 0.5 becomes 0 (free-tier
    # edge, effectively ``None`` is also fine but 0 is clearer for charts).
    return round(cost)


def _dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""


def _accumulate_pg(
    session: Session,
    *,
    tenant_id: str,
    day: date,
    model_name: str,
    agent_name: str,
    input_tokens: int,
    output_tokens: int,
    requests: int,
    cost_delta: int | None,
) -> TokenUsageDaily:
    """PostgreSQL atomic upsert via ``ON CONFLICT DO UPDATE``."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(TokenUsageDaily).values(
        tenant_id=tenant_id,
        day=day,
        model_name=model_name,
        agent_name=agent_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requests=requests,
        cost_usd_cents=cost_delta,
    )
    # Update the running totals atomically using ``excluded.*`` refs.
    # For cost we use COALESCE so existing non-null costs keep their
    # identity when the new call's rate is missing (mirrors the SQL-
    # side semantics of the fallback path).
    stmt = stmt.on_conflict_do_update(
        constraint="uq_token_usage_daily_dim",
        set_={
            "input_tokens": TokenUsageDaily.input_tokens + stmt.excluded.input_tokens,
            "output_tokens": TokenUsageDaily.output_tokens + stmt.excluded.output_tokens,
            "requests": TokenUsageDaily.requests + stmt.excluded.requests,
            "cost_usd_cents": (
                TokenUsageDaily.cost_usd_cents.op("+")(stmt.excluded.cost_usd_cents)
                if cost_delta is not None
                else TokenUsageDaily.cost_usd_cents
            ),
        },
    ).returning(TokenUsageDaily)

    result = session.execute(stmt)
    # ``scalars().one()`` re-hydrates the row as an ORM instance.
    row = result.scalars().one()
    session.flush()
    return row


def _accumulate_fallback(
    session: Session,
    *,
    tenant_id: str,
    day: date,
    model_name: str,
    agent_name: str,
    input_tokens: int,
    output_tokens: int,
    requests: int,
    cost_delta: int | None,
) -> TokenUsageDaily:
    """SQLite / generic upsert: try INSERT inside a SAVEPOINT, on conflict retry with UPDATE.

    The IntegrityError branch covers the race where a concurrent call
    (or this same flow on a second invocation) already inserted the
    row. ``session.begin_nested()`` opens a SAVEPOINT so only the
    failed INSERT is rolled back — any prior uncommitted work in the
    enclosing transaction survives.
    """
    row = TokenUsageDaily(
        tenant_id=tenant_id,
        day=day,
        model_name=model_name,
        agent_name=agent_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requests=requests,
        cost_usd_cents=cost_delta,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
        return row
    except IntegrityError:
        # SAVEPOINT is already rolled back; fall through to UPDATE by
        # unique tuple (atomic under the target row's lock).
        pass

    update_values: dict = {
        "input_tokens": TokenUsageDaily.input_tokens + input_tokens,
        "output_tokens": TokenUsageDaily.output_tokens + output_tokens,
        "requests": TokenUsageDaily.requests + requests,
    }
    if cost_delta is not None:
        # Coalesce so adding a cost to a previously null row works.
        update_values["cost_usd_cents"] = TokenUsageDaily.cost_usd_cents.op("+")(cost_delta)
    session.execute(
        update(TokenUsageDaily)
        .where(
            TokenUsageDaily.tenant_id == tenant_id,
            TokenUsageDaily.day == day,
            TokenUsageDaily.model_name == model_name,
            TokenUsageDaily.agent_name == agent_name,
        )
        .values(**update_values)
    )
    session.flush()
    # Re-fetch so the caller can read updated fields.
    return session.execute(
        select(TokenUsageDaily).where(
            TokenUsageDaily.tenant_id == tenant_id,
            TokenUsageDaily.day == day,
            TokenUsageDaily.model_name == model_name,
            TokenUsageDaily.agent_name == agent_name,
        )
    ).scalar_one()


def accumulate(
    session: Session,
    *,
    tenant_id: str,
    model_name: str,
    agent_name: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    requests: int = 1,
    day: date | None = None,
) -> TokenUsageDaily:
    """Atomic upsert of a ``token_usage_daily`` row.

    Dialect dispatch:

    - PG → ``ON CONFLICT DO UPDATE`` single statement (no race)
    - Other → INSERT-or-UPDATE with ``IntegrityError`` retry (single
      extra round, atomic under the row lock)

    Caller owns commit/rollback. Empty ``model_name`` is allowed — it
    normalises to the literal string ``"unknown"`` so the uniqueness
    key stays stable across calls that legitimately don't know.
    """
    effective_model = model_name or "unknown"
    effective_agent = agent_name or ""
    effective_day = day or _today_utc()
    cost_delta = _compute_cost_cents(effective_model, input_tokens, output_tokens)

    if _dialect_name(session) == "postgresql":
        return _accumulate_pg(
            session,
            tenant_id=tenant_id,
            day=effective_day,
            model_name=effective_model,
            agent_name=effective_agent,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requests=requests,
            cost_delta=cost_delta,
        )
    return _accumulate_fallback(
        session,
        tenant_id=tenant_id,
        day=effective_day,
        model_name=effective_model,
        agent_name=effective_agent,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requests=requests,
        cost_delta=cost_delta,
    )


__all__ = ["accumulate"]
