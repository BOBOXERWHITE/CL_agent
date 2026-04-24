"""create agent_event table with row-level security

Revision ID: 0004_agent_event
Revises: 0003_audit_log
Create Date: 2026-04-22 15:00:00.000000

Structured agent event log introduced in P3.7. Same RLS pattern as
``audit_log``: tenant-scoped reads + explicit GRANT to the app role.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_agent_event"
down_revision: str | Sequence[str] | None = "0003_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "agent_event",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agent_run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False, index=True),
        sa.Column("node_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )

    if not _is_postgres():
        return

    op.execute("ALTER TABLE agent_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_event FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON agent_event
        USING (
            tenant_id = current_setting('app.tenant_id', true)
            OR current_setting('app.tenant_id', true) = '__bypass__'
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'travel_ops_app_user') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON agent_event TO travel_ops_app_user;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON agent_event")
        op.execute("ALTER TABLE agent_event NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE agent_event DISABLE ROW LEVEL SECURITY")
    op.drop_table("agent_event")
