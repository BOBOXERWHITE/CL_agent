"""P6.2: A/B prompt selector tests.

Verifies determinism, traffic-percentage routing, active fallback,
default fallback, and that every call writes a ``prompt_selection_log``
row with the right variant_group + reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.prompt_selection_log import PromptSelectionLog
from app.db.models.prompt_template import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_DRAFT,
    PromptTemplate,
)
from app.services.prompts.selector import select_prompt_variant
from app.services.prompts.service import (
    create_prompt_template,
    transition_prompt_template,
)


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
        prompt_selection_log,
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


def _make_active(session: Session, name: str = "active-v1") -> PromptTemplate:
    row = create_prompt_template(
        session, name=name, task_type="policy_answer", template="active body"
    )
    transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE)
    return row


def _make_candidate(
    session: Session, name: str, traffic: int, body: str = "candidate body"
) -> PromptTemplate:
    row = create_prompt_template(session, name=name, task_type="policy_answer", template=body)
    transition_prompt_template(
        session, row.id, target_status=STATUS_CANDIDATE, traffic_percent=traffic
    )
    return row


def _one_log(session: Session) -> PromptSelectionLog:
    rows = session.query(PromptSelectionLog).all()
    assert len(rows) == 1
    return rows[0]


def test_no_rows_falls_back_to_default(session: Session) -> None:
    sel = select_prompt_variant(session, task_type="policy_answer", tenant_id="t1", request_id="r1")
    assert sel.id is None  # system default
    assert sel.version == 0
    log = _one_log(session)
    assert log.variant_group == "default"
    assert log.selected_reason == "no_db_row"


def test_single_active_selected(session: Session) -> None:
    active = _make_active(session)
    sel = select_prompt_variant(session, task_type="policy_answer", tenant_id="t1", request_id="r1")
    assert sel.id == active.id
    log = _one_log(session)
    assert log.variant_group == "active"
    assert log.selected_reason == "sole_active"


def test_candidate_with_100_traffic_always_wins(session: Session) -> None:
    """traffic_percent=100 on the sole candidate: every tenant lands
    on it regardless of hash bucket."""
    _make_active(session)
    candidate = _make_candidate(session, "c-100", traffic=100)

    for tenant in ("t1", "t2", "t-alice", "t-bob", "whatever"):
        # Fresh row each time — we only check the return value here.
        sel = select_prompt_variant(
            session, task_type="policy_answer", tenant_id=tenant, request_id="r"
        )
        assert sel.id == candidate.id


def test_candidate_with_zero_traffic_never_wins(session: Session) -> None:
    """A 0%-traffic candidate must not be picked — we filter it out in
    the selector. Useful for staging: create a candidate first, dry-run
    on internal tenants, then bump traffic up."""
    active = _make_active(session)
    _make_candidate(session, "c-0", traffic=0)

    for tenant in ("t1", "t2", "t3"):
        sel = select_prompt_variant(
            session, task_type="policy_answer", tenant_id=tenant, request_id="r"
        )
        assert sel.id == active.id


def test_selection_is_deterministic_for_same_tenant(session: Session) -> None:
    """Same tenant_id + task_type → same variant across multiple
    requests. This is the non-negotiable UX property of A/B: users
    don't see the prompt change randomly mid-session.
    """
    _make_active(session)
    _make_candidate(session, "c-50", traffic=50)

    first = select_prompt_variant(
        session, task_type="policy_answer", tenant_id="t-fixed", request_id="r1"
    )
    second = select_prompt_variant(
        session, task_type="policy_answer", tenant_id="t-fixed", request_id="r2"
    )
    third = select_prompt_variant(
        session, task_type="policy_answer", tenant_id="t-fixed", request_id="r3"
    )
    assert first.id == second.id == third.id


def test_traffic_split_approximates_percentage(session: Session) -> None:
    """Across many tenants with traffic_percent=30, roughly 30% should
    land on the candidate. We allow a ±15% slack because sha256 on
    short strings is not perfectly uniform over tiny samples.
    """
    _make_active(session)
    candidate = _make_candidate(session, "c-30", traffic=30)

    n = 200
    on_candidate = 0
    on_active = 0
    for i in range(n):
        sel = select_prompt_variant(
            session, task_type="policy_answer", tenant_id=f"t-{i}", request_id="r"
        )
        if sel.id == candidate.id:
            on_candidate += 1
        else:
            on_active += 1
    ratio = on_candidate / n
    assert 0.15 <= ratio <= 0.45, (
        f"candidate hit rate {ratio:.2%} outside [15%, 45%] for 30% traffic"
    )


def test_multi_candidate_splits_add_up(session: Session) -> None:
    """Two candidates at 25% + 25% + active at 50% — verify the hash
    bucket thresholds compose correctly and sum to 100%.
    """
    active = _make_active(session)
    c1 = _make_candidate(session, "c-a", traffic=25, body="c1")
    c2 = _make_candidate(session, "c-b", traffic=25, body="c2")

    hits = {active.id: 0, c1.id: 0, c2.id: 0}
    for i in range(200):
        sel = select_prompt_variant(
            session, task_type="policy_answer", tenant_id=f"t-{i}", request_id="r"
        )
        assert sel.id in hits
        hits[sel.id] += 1
    # Each candidate should get roughly 25% (±15% slack), active the
    # rest. Most important: all three MUST have received some traffic,
    # otherwise the ordering is broken.
    assert all(v > 0 for v in hits.values()), hits


def test_selection_log_has_trace_context(session: Session) -> None:
    """The log row must carry request_id / session_id for later join
    against RagRecallLog + ChatMessage."""
    _make_active(session)
    rid = str(uuid4())
    sid = str(uuid4())
    select_prompt_variant(
        session,
        task_type="policy_answer",
        tenant_id="t1",
        request_id=rid,
        session_id=sid,
    )
    log = _one_log(session)
    assert log.request_id == rid
    assert log.session_id == sid
    assert log.tenant_id == "t1"


def test_draft_rows_never_selected(session: Session) -> None:
    """A ``draft`` prompt must never be picked — even if no active
    exists we fall through to default instead."""
    row = create_prompt_template(
        session, name="drafty", task_type="policy_answer", template="should-not-appear"
    )
    assert row.status == STATUS_DRAFT

    sel = select_prompt_variant(session, task_type="policy_answer", tenant_id="t1", request_id="r")
    # Falls back to the system default (id=None) because no active row.
    assert sel.id is None
    assert "should-not-appear" not in sel.template


def test_archived_rows_never_selected(session: Session) -> None:
    row = create_prompt_template(
        session, name="old", task_type="policy_answer", template="archived body"
    )
    transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE)
    transition_prompt_template(session, row.id, target_status="archived")

    sel = select_prompt_variant(session, task_type="policy_answer", tenant_id="t1", request_id="r")
    # No active either, so default.
    assert sel.id is None


def test_zero_traffic_candidate_emits_skipped_log_row(session: Session) -> None:
    """P7.5: a 0-traffic candidate shouldn't take traffic (existing
    behaviour) but should leave a ``skipped`` breadcrumb in
    ``prompt_selection_log`` so operators can debug silent
    candidates.
    """
    active = _make_active(session)
    skipped_candidate = _make_candidate(session, "c-zero", traffic=0)

    sel = select_prompt_variant(session, task_type="policy_answer", tenant_id="t1", request_id="r1")
    assert sel.id == active.id  # 0-traffic candidate doesn't win

    logs = session.query(PromptSelectionLog).order_by(PromptSelectionLog.id).all()
    variant_groups = [log.variant_group for log in logs]
    assert "active" in variant_groups
    skipped_rows = [log for log in logs if log.variant_group == "skipped"]
    assert len(skipped_rows) == 1
    assert skipped_rows[0].prompt_template_id == skipped_candidate.id
    assert skipped_rows[0].selected_reason == "candidate_zero_traffic"


def test_multiple_zero_traffic_candidates_logged_individually(
    session: Session,
) -> None:
    """Two candidates at 0% → two ``skipped`` log rows."""
    _make_active(session)
    _make_candidate(session, "c-a", traffic=0)
    _make_candidate(session, "c-b", traffic=0)

    select_prompt_variant(session, task_type="policy_answer", tenant_id="t1", request_id="r1")

    skipped = (
        session.query(PromptSelectionLog)
        .filter(PromptSelectionLog.variant_group == "skipped")
        .all()
    )
    assert len(skipped) == 2


def test_logging_failure_does_not_break_selection(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the log insert throws, the caller must still get a valid
    selection — observability never gates the hot path."""
    active = _make_active(session)

    # Monkeypatch session.add so it raises for PromptSelectionLog but
    # not for other models. We do this via a wrapper that delegates.
    original_add = session.add

    def _faulty_add(instance, *args, **kwargs):
        if isinstance(instance, PromptSelectionLog):
            raise RuntimeError("simulated DB failure")
        return original_add(instance, *args, **kwargs)

    monkeypatch.setattr(session, "add", _faulty_add)

    sel = select_prompt_variant(session, task_type="policy_answer", tenant_id="t1", request_id="r1")
    assert sel.id == active.id
    # No log row was inserted (the failure was swallowed).
    assert session.query(PromptSelectionLog).count() == 0
