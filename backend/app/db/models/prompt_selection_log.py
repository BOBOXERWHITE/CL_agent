"""Per-request record of which prompt variant served which request (P6.2).

Every ``chat.ask`` / agent run goes through ``select_prompt_variant``,
which writes one row here. The row carries enough metadata to:

- join back to the request via ``request_id`` / ``session_id``
- attribute the outcome to a specific prompt version for stats (P6.3)
- debug "why did this user get variant X" via ``selected_reason``

Keeping this as a write-heavy append-only log rather than stuffing it
into ``rag_recall_log`` means the A/B analysis doesn't have to parse
heterogeneous JSON — each row is one flat record.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PromptSelectionLog(Base):
    __tablename__ = "prompt_selection_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # FK omitted deliberately so selection log survives a prompt hard-delete
    # (audit trail); we store the id as a plain string and rely on application
    # code to dereference when displaying.
    prompt_template_id: Mapped[str | None] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Which logical bucket the caller landed in:
    #   "active"          — single-active fallback
    #   "candidate"       — A/B candidate variant
    #   "default"         — system default (no row in DB)
    variant_group: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # Why this variant was picked — useful for debugging rollout
    # surprises and for disambiguating the logs during A/B analysis.
    selected_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
