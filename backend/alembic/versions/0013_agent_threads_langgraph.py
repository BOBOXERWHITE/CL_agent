"""add agent thread / checkpoint tables and thread_id to agent_run

Revision ID: 0013_agent_threads_langgraph
Revises: 0012_rag_recall_log_latency
Create Date: 2026-04-26 18:30:00.000000

Phase 8 promotes ``thread_id`` to the primary conversation/workflow
identity for the new LangGraph-backed policy supervisor. The schema
adds:

- ``agent_thread``: durable multi-run thread state
- ``agent_thread_checkpoint``: persisted LangGraph state snapshots
- ``agent_run.thread_id``: every run belongs to a durable thread
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_agent_threads_langgraph"
down_revision: str | Sequence[str] | None = "0012_rag_recall_log_latency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "agent_thread",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False, server_default="policy"),
        sa.Column(
            "specialist",
            sa.String(length=64),
            nullable=False,
            server_default="generic_policy_agent",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("memory_summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "pending_interrupt_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("latest_checkpoint_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_thread_tenant_id", "agent_thread", ["tenant_id"])
    op.create_index("ix_agent_thread_customer_id", "agent_thread", ["customer_id"])
    op.create_index("ix_agent_thread_domain", "agent_thread", ["domain"])
    op.create_index("ix_agent_thread_status", "agent_thread", ["status"])

    op.add_column("agent_run", sa.Column("thread_id", sa.String(length=36), nullable=True))
    op.create_index("ix_agent_run_thread_id", "agent_run", ["thread_id"])

    op.create_table(
        "agent_thread_checkpoint",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
        sa.Column(
            "checkpoint_type",
            sa.String(length=32),
            nullable=False,
            server_default="langgraph_state",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("state_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "pending_interrupt_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_thread_checkpoint_thread_id", "agent_thread_checkpoint", ["thread_id"]
    )
    op.create_index(
        "ix_agent_thread_checkpoint_agent_run_id",
        "agent_thread_checkpoint",
        ["agent_run_id"],
    )
    op.create_index(
        "ix_agent_thread_checkpoint_status",
        "agent_thread_checkpoint",
        ["status"],
    )

    if _is_postgres():
        op.create_foreign_key(
            "fk_agent_run_thread_id",
            "agent_run",
            "agent_thread",
            ["thread_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_agent_thread_checkpoint_thread_id",
            "agent_thread_checkpoint",
            "agent_thread",
            ["thread_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_agent_thread_checkpoint_agent_run_id",
            "agent_thread_checkpoint",
            "agent_run",
            ["agent_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        """
        INSERT INTO agent_thread (
            id, tenant_id, customer_id, domain, specialist, status,
            memory_summary_json, pending_interrupt_json, latest_checkpoint_id,
            created_at, updated_at
        )
        SELECT
            id,
            tenant_id,
            customer_id,
            CASE
                WHEN route_name = 'ticket_triage' THEN 'ticket'
                WHEN route_name = 'order_anomaly' THEN 'anomaly'
                ELSE 'policy'
            END,
            agent_name,
            CASE
                WHEN status IN ('awaiting_review', 'needs_review') THEN 'awaiting_review'
                WHEN status = 'rejected' THEN 'rejected'
                ELSE 'active'
            END,
            '{}' ,
            '{}' ,
            NULL,
            created_at,
            updated_at
        FROM agent_run
        """
    )
    op.execute("UPDATE agent_run SET thread_id = id WHERE thread_id IS NULL")
    op.alter_column("agent_run", "thread_id", nullable=False)


def downgrade() -> None:
    if _is_postgres():
        op.drop_constraint(
            "fk_agent_thread_checkpoint_agent_run_id",
            "agent_thread_checkpoint",
            type_="foreignkey",
        )
        op.drop_constraint(
            "fk_agent_thread_checkpoint_thread_id",
            "agent_thread_checkpoint",
            type_="foreignkey",
        )
        op.drop_constraint("fk_agent_run_thread_id", "agent_run", type_="foreignkey")
    op.drop_index("ix_agent_thread_checkpoint_status", table_name="agent_thread_checkpoint")
    op.drop_index("ix_agent_thread_checkpoint_agent_run_id", table_name="agent_thread_checkpoint")
    op.drop_index("ix_agent_thread_checkpoint_thread_id", table_name="agent_thread_checkpoint")
    op.drop_table("agent_thread_checkpoint")
    op.drop_index("ix_agent_run_thread_id", table_name="agent_run")
    op.drop_column("agent_run", "thread_id")
    op.drop_index("ix_agent_thread_status", table_name="agent_thread")
    op.drop_index("ix_agent_thread_domain", table_name="agent_thread")
    op.drop_index("ix_agent_thread_customer_id", table_name="agent_thread")
    op.drop_index("ix_agent_thread_tenant_id", table_name="agent_thread")
    op.drop_table("agent_thread")
