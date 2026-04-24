"""create task_run table with row-level security

Revision ID: 0006_task_run
Revises: 0005_agent_memory
Create Date: 2026-04-23 14:00:00.000000

Task observation log introduced in P4.4. Same RLS pattern as
``audit_log`` / ``agent_event`` / ``agent_memory``: tenant-scoped reads +
explicit GRANT to ``travel_ops_app_user``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_task_run"
down_revision: str | Sequence[str] | None = "0005_agent_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "task_run",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("task_name", sa.String(length=128), nullable=False, index=True),
        sa.Column("status", sa.String(length=32), nullable=False, index=True),
        # NULL = no dedupe (multiple NULL rows never collide on the
        # unique constraint — standard SQL semantics).
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trace_id", sa.String(length=64), nullable=False, server_default="", index=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "task_name",
            "idempotency_key",
            name="uq_task_run_tenant_task_idem",
        ),
    )

    if not _is_postgres():
        return

    op.execute("ALTER TABLE task_run ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE task_run FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON task_run
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
                    ON task_run TO travel_ops_app_user;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON task_run")
        op.execute("ALTER TABLE task_run NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE task_run DISABLE ROW LEVEL SECURITY")
    op.drop_table("task_run")
