"""create token_usage_daily aggregate table

Revision ID: 0008_token_usage_daily
Revises: 0007_review_case_agent_run_fk
Create Date: 2026-04-24 12:00:00.000000

P5.2: per-tenant / model / agent daily aggregate for tokens + cost.
RLS follows the existing pattern used by audit_log / agent_event /
agent_memory / task_run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_token_usage_daily"
down_revision: str | Sequence[str] | None = "0007_review_case_agent_run_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "token_usage_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd_cents", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "day",
            "model_name",
            "agent_name",
            name="uq_token_usage_daily_dim",
        ),
    )

    if not _is_postgres():
        return

    op.execute("ALTER TABLE token_usage_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE token_usage_daily FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON token_usage_daily
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
                    ON token_usage_daily TO travel_ops_app_user;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON token_usage_daily")
        op.execute("ALTER TABLE token_usage_daily NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE token_usage_daily DISABLE ROW LEVEL SECURITY")
    op.drop_table("token_usage_daily")
