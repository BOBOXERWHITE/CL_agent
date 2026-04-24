"""User feedback on a chat response attributed to a prompt version (P6.3).

One row per thumbs-up/down click. Joined against
``prompt_selection_log`` to build the stats view that drives promote
decisions (P6.4).

We keep ``comment`` narrow (2 kB) to discourage free-form essay abuse;
richer annotations should land in a dedicated QA table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

RATING_UP = "up"
RATING_DOWN = "down"
ALLOWED_RATINGS = frozenset({RATING_UP, RATING_DOWN})


class PromptFeedback(Base):
    __tablename__ = "prompt_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Version at the moment of feedback — rows retain this even after
    # the prompt has been promoted / archived so the stats stay
    # attributable to the exact text the user saw.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
