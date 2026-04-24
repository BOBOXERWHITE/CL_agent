"""Prompt variant selector with A/B support (P6.2).

The selector decides which ``PromptTemplate`` row serves a given request.
Determinism matters: the same ``(tenant_id, task_type)`` tuple must
always land on the same variant so users don't see a prompt change
mid-session. We hash the tuple to a percentage bucket (0-99) and match
it against candidate ``traffic_percent`` thresholds in a stable order.

Algorithm
---------

    candidates = rows with status=candidate, traffic_percent > 0
                 ordered by version desc, id asc (stable)
    h = sha256(tenant|task_type).hexdigest()[:8] as int mod 100

    cumulative = 0
    for candidate in candidates:
        cumulative += candidate.traffic_percent
        if h < cumulative:
            return candidate, "candidate"

    if active exists:
        return active, "active"
    return default_selection, "default"

Selection is written to ``prompt_selection_log`` so the downstream
feedback aggregator (P6.3) can attribute reward signals back to a
specific version.

``commit`` is default True so the selector is usable from routes
without extra plumbing; pass False when the caller owns the outer
transaction (e.g. inside a single ``/api/chat/ask`` request's atomic
write of ``ChatMessage`` + ``PromptSelectionLog``).
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.prompt_selection_log import PromptSelectionLog
from app.db.models.prompt_template import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    PromptTemplate,
)
from app.services.prompts.service import (
    DEFAULT_POLICY_PROMPT,
    PromptSelection,
)

_log = logging.getLogger(__name__)


def _hash_bucket(tenant_id: str, task_type: str) -> int:
    """Map (tenant, task) → 0..99 deterministically."""
    digest = hashlib.sha256(f"{tenant_id}|{task_type}".encode()).hexdigest()[:8]
    return int(digest, 16) % 100


def _default_selection(task_type: str) -> PromptSelection:
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


def select_prompt_variant(
    session: Session,
    *,
    task_type: str,
    tenant_id: str,
    request_id: str,
    session_id: str | None = None,
    commit: bool = True,
) -> PromptSelection:
    """Pick a prompt variant for the given request and log the decision.

    Returns the ``PromptSelection`` the caller should feed into the
    LLM. The ``PromptSelectionLog`` row is written as a side-effect
    for A/B analysis.
    """
    # All candidates, including 0-traffic ones — we need the 0-traffic
    # rows so P7.5 can log them as "skipped" and operators can debug
    # "why isn't my candidate getting any traffic".
    all_candidates = list(
        session.execute(
            select(PromptTemplate)
            .where(PromptTemplate.task_type == task_type)
            .where(PromptTemplate.status == STATUS_CANDIDATE)
            .order_by(PromptTemplate.version.desc(), PromptTemplate.id.asc())
        ).scalars()
    )
    candidates = [c for c in all_candidates if c.traffic_percent > 0]
    zero_traffic_candidates = [c for c in all_candidates if c.traffic_percent <= 0]
    active = session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.task_type == task_type)
        .where(PromptTemplate.status == STATUS_ACTIVE)
        .order_by(PromptTemplate.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    bucket = _hash_bucket(tenant_id, task_type)
    chosen: PromptTemplate | None = None
    reason = ""
    variant_group = "active"

    if candidates:
        cumulative = 0
        for candidate in candidates:
            cumulative += max(0, min(candidate.traffic_percent, 100))
            if bucket < cumulative:
                chosen = candidate
                reason = f"traffic_routed:bucket={bucket}:cum={cumulative}"
                variant_group = "candidate"
                break

    if chosen is None and active is not None:
        chosen = active
        reason = "sole_active" if not candidates else "fell_through_to_active"
        variant_group = "active"
    # else: no row in DB, will fall back to default_selection below

    if chosen is None:
        selection = _default_selection(task_type)
        _log_selection(
            session,
            request_id=request_id,
            session_id=session_id,
            tenant_id=tenant_id,
            task_type=task_type,
            prompt_template_id=None,
            version=0,
            variant_group="default",
            selected_reason="no_db_row",
            commit=commit,
        )
        return selection

    selection = PromptSelection(
        id=chosen.id,
        name=chosen.name,
        task_type=chosen.task_type,
        template=chosen.template,
        version=chosen.version,
    )
    _log_selection(
        session,
        request_id=request_id,
        session_id=session_id,
        tenant_id=tenant_id,
        task_type=task_type,
        prompt_template_id=chosen.id,
        version=chosen.version,
        variant_group=variant_group,
        selected_reason=reason,
        commit=False,  # P7.5: batch with skipped logs before commit
    )

    # P7.5: emit one ``skipped`` row per 0-traffic candidate so
    # operators can answer "why didn't my candidate see any traffic?"
    # from the log alone (without needing to query prompt_template).
    for skipped in zero_traffic_candidates:
        _log_selection(
            session,
            request_id=request_id,
            session_id=session_id,
            tenant_id=tenant_id,
            task_type=task_type,
            prompt_template_id=skipped.id,
            version=skipped.version,
            variant_group="skipped",
            selected_reason="candidate_zero_traffic",
            commit=False,
        )

    if commit:
        try:
            session.commit()
        except Exception as exc:
            _log.warning("prompt_selection_commit_failed", extra={"error": str(exc)})
            try:
                session.rollback()
            except Exception:
                pass
    return selection


def _log_selection(
    session: Session,
    *,
    request_id: str,
    session_id: str | None,
    tenant_id: str,
    task_type: str,
    prompt_template_id: str | None,
    version: int,
    variant_group: str,
    selected_reason: str,
    commit: bool,
) -> None:
    """Persist one ``PromptSelectionLog`` row.

    Wrapped in a try/except so a logging failure (e.g. DB hiccup) never
    escalates a chat response to a 5xx — we'd rather miss a log row
    than break the user's request. That's the same trade-off we make
    for ``token_usage`` and ``audit_log``.
    """
    try:
        session.add(
            PromptSelectionLog(
                request_id=request_id,
                session_id=session_id,
                tenant_id=tenant_id,
                task_type=task_type,
                prompt_template_id=prompt_template_id,
                version=version,
                variant_group=variant_group,
                selected_reason=selected_reason,
            )
        )
        if commit:
            session.commit()
        else:
            session.flush()
    except Exception as exc:
        _log.warning(
            "prompt_selection_log_failed",
            extra={
                "error": str(exc),
                "request_id": request_id,
                "tenant_id": tenant_id,
                "task_type": task_type,
            },
        )
        if commit:
            try:
                session.rollback()
            except Exception:
                pass


__all__ = ["select_prompt_variant"]
