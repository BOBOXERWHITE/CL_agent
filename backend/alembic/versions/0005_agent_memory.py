"""create agent_memory table with row-level security

Revision ID: 0005_agent_memory
Revises: 0004_agent_event
Create Date: 2026-04-22 16:00:00.000000

Long-term semantic memory introduced in P3.6. Same RLS pattern as
``audit_log`` / ``agent_event``: tenant-scoped reads + explicit GRANT to
``travel_ops_app_user``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_agent_memory"
down_revision: str | Sequence[str] | None = "0004_agent_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("key", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
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

    op.execute("ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_memory FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON agent_memory
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
                    ON agent_memory TO travel_ops_app_user;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON agent_memory")
        op.execute("ALTER TABLE agent_memory NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE agent_memory DISABLE ROW LEVEL SECURITY")
    op.drop_table("agent_memory")
