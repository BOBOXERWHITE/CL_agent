from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.prompt_template import (
    ALLOWED_STATUSES,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_CANDIDATE,
    STATUS_DRAFT,
    PromptTemplate,
)

DEFAULT_POLICY_PROMPT = """你是企业差旅政策助手。请只基于给定证据回答问题。
如果证据不足，请明确说明证据不足。
回答时优先给出结论，再说明依据。"""


class PromptStateError(ValueError):
    """Raised on an illegal state transition or invalid ``traffic_percent``."""


# Legal transitions (P6.1 state machine). Operators always go
# edit → candidate → active, and any state can be archived. Reverting
# from archived requires ``draft`` first so the "edit before rollout"
# invariant stays intact (a true rollback endpoint in P6.4 wraps this).
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_DRAFT: frozenset({STATUS_CANDIDATE, STATUS_ACTIVE, STATUS_ARCHIVED}),
    STATUS_CANDIDATE: frozenset({STATUS_ACTIVE, STATUS_ARCHIVED, STATUS_DRAFT}),
    STATUS_ACTIVE: frozenset({STATUS_ARCHIVED}),
    STATUS_ARCHIVED: frozenset({STATUS_DRAFT}),
}


@dataclass(frozen=True)
class PromptSelection:
    id: str | None
    name: str
    task_type: str
    template: str
    version: int


def list_prompt_templates(session: Session) -> list[PromptTemplate]:
    rows = session.execute(
        select(PromptTemplate).order_by(
            PromptTemplate.task_type.asc(), PromptTemplate.version.desc()
        )
    ).scalars()
    return list(rows)


def create_prompt_template(
    session: Session,
    *,
    name: str,
    task_type: str,
    template: str,
) -> PromptTemplate:
    next_version = (
        session.execute(
            select(func.coalesce(func.max(PromptTemplate.version), 0)).where(
                PromptTemplate.task_type == task_type
            )
        ).scalar_one()
        + 1
    )

    prompt_template = PromptTemplate(
        id=str(uuid4()),
        name=name,
        task_type=task_type,
        template=template,
        version=next_version,
        status=STATUS_DRAFT,
        traffic_percent=0,
    )
    session.add(prompt_template)
    session.commit()
    session.refresh(prompt_template)
    return prompt_template


def activate_prompt_template(session: Session, prompt_template_id: str) -> PromptTemplate:
    """Legacy P0 API: force-activate one template.

    Kept for callers (and tests) that pre-date P6.1's explicit state
    machine. The legacy contract demotes every other same-task_type row
    to ``draft`` — we preserve that contract. New code should go
    through :func:`transition_prompt_template` which does proper
    ``active → archived`` transitions.
    """
    prompt_template = session.get(PromptTemplate, prompt_template_id)
    if prompt_template is None:
        raise LookupError(prompt_template_id)

    session.execute(
        PromptTemplate.__table__.update()
        .where(PromptTemplate.task_type == prompt_template.task_type)
        .values(status=STATUS_DRAFT, traffic_percent=0)
    )
    prompt_template.status = STATUS_ACTIVE
    prompt_template.traffic_percent = 0
    session.add(prompt_template)
    session.commit()
    session.refresh(prompt_template)
    return prompt_template


def transition_prompt_template(
    session: Session,
    prompt_template_id: str,
    *,
    target_status: str,
    traffic_percent: int = 0,
    commit: bool = True,
) -> PromptTemplate:
    """P6.1: explicit state-machine transition with validation.

    Raises :class:`PromptStateError` when:
    - the target status isn't one of the four canonical values
    - the transition from the current status isn't in the allowed map
    - ``traffic_percent`` is outside ``[0, 100]``
    - setting ``traffic_percent > 0`` on a non-candidate status

    When promoting to ``active``, any other same-task_type row currently
    in ``active`` or ``candidate`` gets moved to ``archived`` so there's
    always exactly one main production version.
    """
    if target_status not in ALLOWED_STATUSES:
        raise PromptStateError(f"unknown target_status {target_status!r}")
    if not 0 <= traffic_percent <= 100:
        raise PromptStateError("traffic_percent must be in [0, 100]")
    if traffic_percent > 0 and target_status != STATUS_CANDIDATE:
        raise PromptStateError("traffic_percent > 0 only makes sense for status=candidate")

    row = session.get(PromptTemplate, prompt_template_id)
    if row is None:
        raise LookupError(prompt_template_id)

    if target_status == row.status:
        # Idempotent: same state, possibly updated traffic_percent on a
        # candidate — allow it without going through the transition map.
        if target_status == STATUS_CANDIDATE:
            row.traffic_percent = traffic_percent
            session.add(row)
            if commit:
                session.commit()
                session.refresh(row)
            return row
        return row

    allowed = _ALLOWED_TRANSITIONS[row.status]
    if target_status not in allowed:
        raise PromptStateError(
            f"cannot transition {row.status!r} → {target_status!r}; "
            f"allowed next states: {sorted(allowed)}"
        )

    # When a new row enters ``active``, archive any existing active /
    # candidate rows for the same task_type so the invariants hold:
    #   - at most one active
    #   - only candidates can have traffic_percent > 0
    if target_status == STATUS_ACTIVE:
        session.execute(
            PromptTemplate.__table__.update()
            .where(PromptTemplate.task_type == row.task_type)
            .where(PromptTemplate.id != row.id)
            .where(PromptTemplate.status.in_([STATUS_ACTIVE, STATUS_CANDIDATE]))
            .values(status=STATUS_ARCHIVED, traffic_percent=0)
        )

    row.status = target_status
    # traffic_percent only meaningful on candidate.
    row.traffic_percent = traffic_percent if target_status == STATUS_CANDIDATE else 0
    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    return row


def get_prompt_selection(session: Session, task_type: str) -> PromptSelection:
    """Pick a single prompt for ``task_type``.

    P6.1 fallback semantics (pre-A/B): return the highest-version
    ``active`` row, or the system default when nothing is active. P6.2
    will add candidate-aware hash-based selection on top of this
    helper without changing the function signature (callers that need
    A/B pass a tenant_id to ``select_prompt_variant`` — see P6.2).
    """
    prompt_template = session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.task_type == task_type)
        .where(PromptTemplate.status == STATUS_ACTIVE)
        .order_by(PromptTemplate.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    if prompt_template is not None:
        return PromptSelection(
            id=prompt_template.id,
            name=prompt_template.name,
            task_type=prompt_template.task_type,
            template=prompt_template.template,
            version=prompt_template.version,
        )

    if task_type == "policy_answer":
        return PromptSelection(
            id=None,
            name="系统默认政策问答 Prompt",
            task_type=task_type,
            template=DEFAULT_POLICY_PROMPT,
            version=0,
        )

    return PromptSelection(
        id=None,
        name=f"系统默认 {task_type} Prompt",
        task_type=task_type,
        template="请根据上下文完成当前任务。",
        version=0,
    )


__all__ = [
    "DEFAULT_POLICY_PROMPT",
    "PromptSelection",
    "PromptStateError",
    "activate_prompt_template",
    "create_prompt_template",
    "get_prompt_selection",
    "list_prompt_templates",
    "transition_prompt_template",
]
