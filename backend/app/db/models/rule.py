from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class PolicyRule(Base):
    __tablename__ = "policy_rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expense_type: Mapped[str] = mapped_column(String(64), index=True)
    city_tier: Mapped[str] = mapped_column(String(32), index=True)
    threshold_amount: Mapped[float] = mapped_column(Float)
    decision_on_exceed: Mapped[str] = mapped_column(String(32), default="blocked")
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReviewCase(Base):
    __tablename__ = "review_case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    suggested_action: Mapped[str] = mapped_column(String(64), default="转人工复核")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rule_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # P5.4: explicit FK to the triggering agent run (nullable: older
    # review cases + non-agent sources don't have one). Populated by
    # ``create_review_case(..., agent_run_id=run_id)``. The old
    # ``payload_json.agent_run_id`` field is still written for a
    # transition period so existing consumers don't break.
    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    @property
    def rule_result(self) -> dict[str, Any]:
        return self.rule_result_json
