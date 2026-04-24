"""create prompt_selection_log table with row-level security

Revision ID: 0010_prompt_selection_log
Revises: 0009_prompt_traffic_percent
Create Date: 2026-04-25 10:00:00.000000

P6.2: per-request selection log for A/B analysis. Same RLS pattern as
other tenant-scoped tables (audit_log / agent_event / token_usage).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_prompt_selection_log"
down_revision: str | Sequence[str] | None = "0009_prompt_traffic_percent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "prompt_selection_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("session_id", sa.String(length=64), nullable=True, index=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("task_type", sa.String(length=64), nullable=False, index=True),
        sa.Column("prompt_template_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "variant_group",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "selected_reason",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
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

    op.execute("ALTER TABLE prompt_selection_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_selection_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON prompt_selection_log
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
                    ON prompt_selection_log TO travel_ops_app_user;
                -- id is SERIAL / autoincrement; grant USAGE on the sequence
                -- so inserts don't fail with permission-denied on the
                -- sequence nextval.
                EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO travel_ops_app_user';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON prompt_selection_log")
        op.execute("ALTER TABLE prompt_selection_log NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE prompt_selection_log DISABLE ROW LEVEL SECURITY")
    op.drop_table("prompt_selection_log")
