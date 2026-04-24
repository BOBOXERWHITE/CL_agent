"""Audit log table — append-only record of every state-changing action.

Why a dedicated table instead of a log file:
- Queryable by tenant_id / user_id / action / time range from the same DB
  the rest of the app uses; no extra log shipping infra needed for a PoC.
- Tenant-scoped via the same RLS policy as the business tables, so a
  reviewer can pull "all audit events for my tenant" without leaking
  other tenants' history.
- Survives application restarts (file logs in containers don't).

Fields are intentionally narrow:
- ``action`` is a dotted string ("chat.ask", "agent.run") for easy grep
  and metric tagging.
- ``payload_json`` carries a *sanitised* summary of the input -- never the
  raw user prompt, never tokens, never passwords. Callers are responsible
  for sanitisation; ``app.core.audit.record_audit`` strips known secrets
  defensively.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
