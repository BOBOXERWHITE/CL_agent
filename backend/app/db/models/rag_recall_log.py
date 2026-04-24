from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class RagRecallLog(Base):
    __tablename__ = "rag_recall_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    retrieval_mode: Mapped[str] = mapped_column(String(32))
    prompt_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    prompt_name: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(128))
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    token_usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trace_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # P7.3: request-level latency (retrieval + generation + cache) so
    # ``/api/prompts/{id}/stats`` and ``/api/health/slo`` can compute
    # real p50 / p95 numbers instead of null placeholders.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # P7.3: pull the answer confidence out of trace_json into a column
    # so stats queries can ``AVG()`` it without JSON path extraction —
    # the latter is dialect-specific (PG vs SQLite) and made the
    # original stats code return a literal NULL everywhere.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
