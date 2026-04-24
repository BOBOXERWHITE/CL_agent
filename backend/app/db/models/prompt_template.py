from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


# P6.1 status vocabulary
# ----------------------
# - ``draft``     : editable; not selected at runtime
# - ``candidate`` : A/B-tested; partially selected by ``traffic_percent`` (P6.2)
# - ``active``    : main version for a task_type (ideally unique when not A/Bing)
# - ``archived``  : retired; kept for audit / rollback, never auto-selected
STATUS_DRAFT = "draft"
STATUS_CANDIDATE = "candidate"
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"

ALLOWED_STATUSES = frozenset({STATUS_DRAFT, STATUS_CANDIDATE, STATUS_ACTIVE, STATUS_ARCHIVED})


class PromptTemplate(Base):
    __tablename__ = "prompt_template"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    template: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), index=True, default=STATUS_DRAFT)
    # P6.1: 0 = no traffic (candidate still invisible; use to stage the
    # rollout); 100 = full traffic (equivalent to promoting to active).
    # Only meaningful for status=candidate; ignored elsewhere.
    traffic_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
