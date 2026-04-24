"""create prompt_feedback table with row-level security

Revision ID: 0011_prompt_feedback
Revises: 0010_prompt_selection_log
Create Date: 2026-04-25 11:00:00.000000

P6.3: thumbs up/down feedback per ``ChatSession``. Tenant-scoped
RLS + GRANT to travel_ops_app_user follows the established pattern.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_prompt_feedback"
down_revision: str | Sequence[str] | None = "0010_prompt_selection_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "prompt_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("prompt_template_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rating", sa.String(length=8), nullable=False, index=True),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
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

    op.execute("ALTER TABLE prompt_feedback ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_feedback FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON prompt_feedback
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
                    ON prompt_feedback TO travel_ops_app_user;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON prompt_feedback")
        op.execute("ALTER TABLE prompt_feedback NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE prompt_feedback DISABLE ROW LEVEL SECURITY")
    op.drop_table("prompt_feedback")
