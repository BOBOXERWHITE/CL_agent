"""Unit tests for P5.2 token usage sink."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.token_usage import TokenUsageDaily
from app.services.observability import token_sink


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", future=True)
    from app.db.models import (  # noqa: F401
        agent,
        agent_event,
        agent_memory,
        audit_log,
        conversation,
        eval,
        knowledge,
        prompt_template,
        rag_recall_log,
        rule,
        runtime_log,
        system_setting,
        task_run,
        token_usage,
    )

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def test_first_accumulate_inserts_new_row(session: Session) -> None:
    row = token_sink.accumulate(
        session,
        tenant_id="t1",
        model_name="gpt-4",
        agent_name="chat",
        input_tokens=100,
        output_tokens=50,
    )
    session.commit()

    assert row.tenant_id == "t1"
    assert row.input_tokens == 100
    assert row.output_tokens == 50
    assert row.requests == 1
    # No COST_RATE_* env → cost stays null.
    assert row.cost_usd_cents is None


def test_second_accumulate_same_dims_aggregates(session: Session) -> None:
    token_sink.accumulate(
        session,
        tenant_id="t1",
        model_name="gpt-4",
        agent_name="chat",
        input_tokens=10,
        output_tokens=5,
    )
    token_sink.accumulate(
        session,
        tenant_id="t1",
        model_name="gpt-4",
        agent_name="chat",
        input_tokens=20,
        output_tokens=15,
    )
    session.commit()

    rows = session.query(TokenUsageDaily).all()
    assert len(rows) == 1
    assert rows[0].input_tokens == 30
    assert rows[0].output_tokens == 20
    assert rows[0].requests == 2


def test_different_dimensions_create_separate_rows(session: Session) -> None:
    token_sink.accumulate(session, tenant_id="t1", model_name="gpt-4", input_tokens=10)
    token_sink.accumulate(session, tenant_id="t1", model_name="claude-3", input_tokens=10)
    # Different agents also separate.
    token_sink.accumulate(
        session, tenant_id="t1", model_name="gpt-4", agent_name="chat", input_tokens=10
    )
    token_sink.accumulate(
        session, tenant_id="t1", model_name="gpt-4", agent_name="policy", input_tokens=10
    )
    session.commit()
    # 4 distinct tuples → 4 rows.
    assert session.query(TokenUsageDaily).count() == 4


def test_tenant_isolation_in_upsert(session: Session) -> None:
    """(t1, gpt-4, '') and (t2, gpt-4, '') are separate rows even though
    only tenant_id differs — unique constraint is per-tenant."""
    token_sink.accumulate(session, tenant_id="t1", model_name="gpt-4", input_tokens=10)
    token_sink.accumulate(session, tenant_id="t2", model_name="gpt-4", input_tokens=10)
    session.commit()
    assert session.query(TokenUsageDaily).count() == 2


def test_missing_model_name_falls_back_to_unknown(session: Session) -> None:
    row = token_sink.accumulate(session, tenant_id="t1", model_name="", input_tokens=5)
    session.commit()
    assert row.model_name == "unknown"


def test_cost_computed_when_rate_configured(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``COST_RATE_GPT_4_INPUT_PER_1K_CENTS=3`` means 3 cents per 1k input
    tokens; 1000 input tokens = 3 cents."""
    monkeypatch.setenv("COST_RATE_GPT_4_INPUT_PER_1K_CENTS", "3")
    monkeypatch.setenv("COST_RATE_GPT_4_OUTPUT_PER_1K_CENTS", "6")

    row = token_sink.accumulate(
        session,
        tenant_id="t1",
        model_name="gpt-4",
        input_tokens=1000,
        output_tokens=500,
    )
    session.commit()
    # 1000 in * 3c/1k + 500 out * 6c/1k = 3 + 3 = 6 cents.
    assert row.cost_usd_cents == 6


def test_cost_accumulates_across_calls(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COST_RATE_GPT_4_INPUT_PER_1K_CENTS", "3")
    token_sink.accumulate(session, tenant_id="t1", model_name="gpt-4", input_tokens=1000)
    token_sink.accumulate(session, tenant_id="t1", model_name="gpt-4", input_tokens=2000)
    session.commit()
    row = session.query(TokenUsageDaily).one()
    # 3c + 6c = 9c
    assert row.cost_usd_cents == 9


def test_missing_cost_rate_leaves_cost_null(session: Session) -> None:
    row = token_sink.accumulate(
        session,
        tenant_id="t1",
        model_name="custom-model",
        input_tokens=1000,
        output_tokens=500,
    )
    session.commit()
    assert row.cost_usd_cents is None


def test_malformed_cost_rate_is_ignored(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bad env value must not crash the sink — observability never
    escalates to 5xx."""
    monkeypatch.setenv("COST_RATE_GPT_4_INPUT_PER_1K_CENTS", "not-a-number")
    row = token_sink.accumulate(session, tenant_id="t1", model_name="gpt-4", input_tokens=1000)
    session.commit()
    assert row.cost_usd_cents is None


def test_different_days_create_separate_rows(session: Session) -> None:
    today = date(2026, 4, 24)
    yesterday = today - timedelta(days=1)
    token_sink.accumulate(
        session, tenant_id="t1", model_name="gpt-4", input_tokens=10, day=yesterday
    )
    token_sink.accumulate(session, tenant_id="t1", model_name="gpt-4", input_tokens=10, day=today)
    session.commit()
    assert session.query(TokenUsageDaily).count() == 2


# ---------------------------------------------------------------------------
# P5-patch-B: concurrent / race handling
# ---------------------------------------------------------------------------


def test_concurrent_insert_race_resolved_via_update(session: Session) -> None:
    """Simulate the "two workers flush at once" race: manually insert
    the row behind the sink's back, then call ``accumulate`` — the
    INSERT savepoint must fail on the unique constraint and the
    fallback UPDATE branch must merge the deltas in.

    Before P5-patch-B this used to blow up with IntegrityError since
    the sink did SELECT + INSERT non-atomically.
    """
    from datetime import date

    today = date(2026, 4, 24)
    # Simulate another worker's earlier write.
    session.add(
        TokenUsageDaily(
            tenant_id="t1",
            day=today,
            model_name="gpt-4",
            agent_name="chat",
            input_tokens=50,
            output_tokens=25,
            requests=1,
            cost_usd_cents=None,
        )
    )
    session.commit()

    # Now accumulate on the same key — the SAVEPOINT INSERT will
    # conflict; the fallback UPDATE must add the new deltas.
    row = token_sink.accumulate(
        session,
        tenant_id="t1",
        model_name="gpt-4",
        agent_name="chat",
        input_tokens=30,
        output_tokens=10,
        day=today,
    )
    session.commit()

    assert row.input_tokens == 80
    assert row.output_tokens == 35
    assert row.requests == 2
    assert session.query(TokenUsageDaily).count() == 1


def test_many_sequential_accumulates_single_row(session: Session) -> None:
    """100 small accumulates on the same key → exactly 1 row with
    all deltas merged. Sanity that the savepoint fallback isn't
    silently dropping writes."""
    for _ in range(100):
        token_sink.accumulate(session, tenant_id="t1", model_name="gpt-4", input_tokens=1)
    session.commit()
    rows = session.query(TokenUsageDaily).all()
    assert len(rows) == 1
    assert rows[0].input_tokens == 100
    assert rows[0].requests == 100


def test_concurrent_insert_preserves_null_cost_when_new_is_null(
    session: Session,
) -> None:
    """If an existing row has ``cost_usd_cents=None`` and a new delta
    also has no cost (no rate configured), the merged row must stay
    None — not 0."""
    from datetime import date

    today = date(2026, 4, 24)
    session.add(
        TokenUsageDaily(
            tenant_id="t1",
            day=today,
            model_name="unknown-model",
            agent_name="",
            input_tokens=10,
            output_tokens=5,
            requests=1,
            cost_usd_cents=None,
        )
    )
    session.commit()

    row = token_sink.accumulate(
        session,
        tenant_id="t1",
        model_name="unknown-model",
        input_tokens=20,
        output_tokens=10,
        day=today,
    )
    session.commit()

    assert row.cost_usd_cents is None
    assert row.input_tokens == 30
