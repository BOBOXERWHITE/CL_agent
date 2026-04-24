"""Prompt-level stats aggregation (P6.3 + P7.3).

Joins three tables:

- ``prompt_selection_log`` — how many times the variant was selected
- ``prompt_feedback`` — up / down counts per variant
- ``rag_recall_log`` — avg confidence + avg latency (P7.3 uses the
  first-class ``confidence`` + ``latency_ms`` columns instead of the
  dialect-specific JSON-path extraction the P6.3 version used)

Kept as small module-level functions so routes can call them without
instantiating a service class. All queries are scoped to the caller's
tenant by the normal ``_apply_tenant_scope`` middleware (PG + RLS) or
by the SQLite test environment's per-test DB.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.prompt_feedback import RATING_DOWN, RATING_UP, PromptFeedback
from app.db.models.prompt_selection_log import PromptSelectionLog
from app.db.models.prompt_template import PromptTemplate
from app.db.models.rag_recall_log import RagRecallLog


@dataclass(frozen=True)
class PromptStats:
    prompt_template_id: str
    version: int
    status: str
    total_requests: int
    up_count: int
    down_count: int
    up_rate: float | None
    avg_confidence: float | None
    avg_latency_ms: float | None


def compute_prompt_stats(session: Session, *, prompt_template_id: str) -> PromptStats | None:
    """Return the aggregated stats for one prompt version, or None if
    the template id isn't found."""
    row = session.get(PromptTemplate, prompt_template_id)
    if row is None:
        return None

    total_requests = int(
        session.execute(
            select(func.count())
            .select_from(PromptSelectionLog)
            .where(PromptSelectionLog.prompt_template_id == prompt_template_id)
        ).scalar_one()
    )
    up_count = int(
        session.execute(
            select(func.count())
            .select_from(PromptFeedback)
            .where(PromptFeedback.prompt_template_id == prompt_template_id)
            .where(PromptFeedback.rating == RATING_UP)
        ).scalar_one()
    )
    down_count = int(
        session.execute(
            select(func.count())
            .select_from(PromptFeedback)
            .where(PromptFeedback.prompt_template_id == prompt_template_id)
            .where(PromptFeedback.rating == RATING_DOWN)
        ).scalar_one()
    )
    rated = up_count + down_count
    up_rate = (up_count / rated) if rated > 0 else None

    # P7.3: avg over the new first-class ``latency_ms`` + ``confidence``
    # columns. Rows written before the migration land here with NULL,
    # so ``func.avg`` ignores them — the average only reflects
    # P7.3-or-later requests.
    recall_stats = session.execute(
        select(
            func.avg(RagRecallLog.latency_ms),
            func.avg(RagRecallLog.confidence),
        ).where(RagRecallLog.prompt_template_id == prompt_template_id)
    ).one()
    avg_latency_ms = float(recall_stats[0]) if recall_stats[0] is not None else None
    avg_confidence = float(recall_stats[1]) if recall_stats[1] is not None else None

    return PromptStats(
        prompt_template_id=prompt_template_id,
        version=row.version,
        status=row.status,
        total_requests=total_requests,
        up_count=up_count,
        down_count=down_count,
        up_rate=up_rate,
        avg_confidence=avg_confidence,
        avg_latency_ms=avg_latency_ms,
    )


__all__ = ["PromptStats", "compute_prompt_stats"]
