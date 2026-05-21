from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class AgentRun(Base):
    __tablename__ = "agent_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_thread.id", ondelete="CASCADE"),
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    route_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timeline_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    thread: Mapped[AgentThread | None] = relationship(back_populates="runs")
    tool_calls: Mapped[list[ToolCallLog]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        order_by="ToolCallLog.created_at",
    )
    checkpoints: Mapped[list[AgentThreadCheckpoint]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        order_by="AgentThreadCheckpoint.created_at",
    )


class AgentThread(Base):
    __tablename__ = "agent_thread"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    domain: Mapped[str] = mapped_column(String(32), default="policy", index=True)
    specialist: Mapped[str] = mapped_column(String(64), default="generic_policy_agent")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    memory_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending_interrupt_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latest_checkpoint_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    runs: Mapped[list[AgentRun]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="AgentRun.created_at",
    )
    checkpoints: Mapped[list[AgentThreadCheckpoint]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="AgentThreadCheckpoint.created_at",
    )


class AgentThreadCheckpoint(Base):
    __tablename__ = "agent_thread_checkpoint"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_thread.id", ondelete="CASCADE"),
        index=True,
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    checkpoint_type: Mapped[str] = mapped_column(String(32), default="langgraph_state")
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending_interrupt_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    thread: Mapped[AgentThread] = relationship(back_populates="checkpoints")
    agent_run: Mapped[AgentRun | None] = relationship(back_populates="checkpoints")


class ToolCallLog(Base):
    __tablename__ = "tool_call_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_run.id", ondelete="CASCADE"),
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent_run: Mapped[AgentRun] = relationship(back_populates="tool_calls")
