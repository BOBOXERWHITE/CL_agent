"""P6.1: state-machine transitions for PromptTemplate.

Verifies the allowed graph + traffic_percent validation:

    draft ↔ candidate → active → archived
        ↑                  ↑
        └──────────────────┘

Tested via the ``transition_prompt_template`` service (the P6.4 API
will layer on top without redoing validation).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.prompt_template import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_CANDIDATE,
    STATUS_DRAFT,
    PromptTemplate,
)
from app.services.prompts.service import (
    PromptStateError,
    activate_prompt_template,
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


def _make(session: Session, name: str = "p1", task: str = "policy_answer") -> PromptTemplate:
    return create_prompt_template(session, name=name, task_type=task, template="t")


def test_create_starts_in_draft_with_zero_traffic(session: Session) -> None:
    row = _make(session)
    assert row.status == STATUS_DRAFT
    assert row.traffic_percent == 0


def test_draft_to_candidate_sets_traffic(session: Session) -> None:
    row = _make(session)
    updated = transition_prompt_template(
        session,
        row.id,
        target_status=STATUS_CANDIDATE,
        traffic_percent=25,
    )
    assert updated.status == STATUS_CANDIDATE
    assert updated.traffic_percent == 25


def test_candidate_to_active_archives_previous_active(session: Session) -> None:
    """Promoting a candidate must archive any existing active row for
    the same task_type — the "one active per task" invariant."""
    old = _make(session, name="old")
    transition_prompt_template(session, old.id, target_status=STATUS_ACTIVE)
    new = _make(session, name="new")
    transition_prompt_template(session, new.id, target_status=STATUS_CANDIDATE, traffic_percent=20)

    transition_prompt_template(session, new.id, target_status=STATUS_ACTIVE)

    session.refresh(old)
    session.refresh(new)
    assert old.status == STATUS_ARCHIVED
    assert old.traffic_percent == 0
    assert new.status == STATUS_ACTIVE
    # traffic_percent resets when leaving candidate.
    assert new.traffic_percent == 0


def test_active_to_archived_allowed(session: Session) -> None:
    row = _make(session)
    transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE)
    transition_prompt_template(session, row.id, target_status=STATUS_ARCHIVED)
    session.refresh(row)
    assert row.status == STATUS_ARCHIVED


def test_archived_cannot_directly_go_active(session: Session) -> None:
    """Archived → active must go via draft first. This preserves the
    "edit before rollout" invariant."""
    row = _make(session)
    transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE)
    transition_prompt_template(session, row.id, target_status=STATUS_ARCHIVED)

    with pytest.raises(PromptStateError, match="cannot transition"):
        transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE)


def test_archived_to_draft_then_active_works(session: Session) -> None:
    """The canonical rollback path: archived → draft → active."""
    row = _make(session)
    transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE)
    transition_prompt_template(session, row.id, target_status=STATUS_ARCHIVED)
    transition_prompt_template(session, row.id, target_status=STATUS_DRAFT)
    transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE)
    session.refresh(row)
    assert row.status == STATUS_ACTIVE


def test_traffic_percent_out_of_range_rejected(session: Session) -> None:
    row = _make(session)
    with pytest.raises(PromptStateError, match="traffic_percent"):
        transition_prompt_template(
            session, row.id, target_status=STATUS_CANDIDATE, traffic_percent=150
        )
    with pytest.raises(PromptStateError, match="traffic_percent"):
        transition_prompt_template(
            session, row.id, target_status=STATUS_CANDIDATE, traffic_percent=-1
        )


def test_traffic_percent_on_non_candidate_rejected(session: Session) -> None:
    """Setting ``traffic_percent > 0`` on any non-candidate status is a
    programmer error — the column is ignored there, we fail loud."""
    row = _make(session)
    with pytest.raises(PromptStateError, match="only makes sense"):
        transition_prompt_template(session, row.id, target_status=STATUS_ACTIVE, traffic_percent=50)


def test_same_state_candidate_updates_traffic_idempotently(session: Session) -> None:
    """A candidate staying a candidate with a new traffic % is allowed —
    staging a rollout from 10% → 50% is a common case and shouldn't
    require archiving first.
    """
    row = _make(session)
    transition_prompt_template(session, row.id, target_status=STATUS_CANDIDATE, traffic_percent=10)
    transition_prompt_template(session, row.id, target_status=STATUS_CANDIDATE, traffic_percent=50)
    session.refresh(row)
    assert row.status == STATUS_CANDIDATE
    assert row.traffic_percent == 50


def test_unknown_target_status_rejected(session: Session) -> None:
    row = _make(session)
    with pytest.raises(PromptStateError, match="unknown target_status"):
        transition_prompt_template(session, row.id, target_status="superactive")


def test_candidate_can_revert_to_draft(session: Session) -> None:
    row = _make(session)
    transition_prompt_template(session, row.id, target_status=STATUS_CANDIDATE, traffic_percent=30)
    transition_prompt_template(session, row.id, target_status=STATUS_DRAFT)
    session.refresh(row)
    assert row.status == STATUS_DRAFT
    assert row.traffic_percent == 0  # reset when leaving candidate


def test_unknown_prompt_id_raises_lookup_error(session: Session) -> None:
    with pytest.raises(LookupError):
        transition_prompt_template(session, "does-not-exist", target_status=STATUS_CANDIDATE)


def test_legacy_activate_preserves_draft_demotion_contract(session: Session) -> None:
    """The legacy ``activate_prompt_template`` path demotes every other
    same-task_type row to ``draft`` — existing API consumers depend on
    this. We preserve it instead of flipping siblings to archived.
    """
    a = _make(session, name="A")
    b = _make(session, name="B")

    activate_prompt_template(session, a.id)
    activate_prompt_template(session, b.id)

    session.refresh(a)
    session.refresh(b)
    assert a.status == STATUS_DRAFT  # legacy contract
    assert b.status == STATUS_ACTIVE


def test_only_one_active_per_task_after_promote(session: Session) -> None:
    """Invariant: after promoting a second template to active via the
    new state machine, there is exactly one active row per task_type."""
    a = _make(session, name="A")
    b = _make(session, name="B")
    transition_prompt_template(session, a.id, target_status=STATUS_ACTIVE)
    transition_prompt_template(session, b.id, target_status=STATUS_ACTIVE)

    actives = (
        session.query(PromptTemplate)
        .filter(
            PromptTemplate.task_type == "policy_answer",
            PromptTemplate.status == STATUS_ACTIVE,
        )
        .count()
    )
    assert actives == 1
