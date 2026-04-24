"""create audit_log table with row-level security

Revision ID: 0003_audit_log
Revises: 0002_enable_rls
Create Date: 2026-04-20 14:00:00.000000

Adds the ``audit_log`` table and applies the same RLS pattern established in
0002 so reviewers can only read their own tenant's audit history. The table
is append-only by convention; we don't add a UNIQUE constraint on
(action, target_id) because the same target can be touched many times.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_audit_log"
down_revision: str | Sequence[str] | None = "0002_enable_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("action", sa.String(length=64), nullable=False, index=True),
        sa.Column("target_type", sa.String(length=64), nullable=True, index=True),
        sa.Column("target_id", sa.String(length=64), nullable=True, index=True),
        sa.Column("request_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
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

    # Match the 0002 pattern: tenants can only see their own rows.
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_log
        USING (
            tenant_id = current_setting('app.tenant_id', true)
            OR current_setting('app.tenant_id', true) = '__bypass__'
        )
        """
    )
    # The 0002 migration created travel_ops_app_user, but if 0002 ran in a
    # separate alembic invocation that's been rolled back (e.g. partial
    # failure on first attempt), the role might be missing. Re-create
    # defensively with a DO block; this also keeps 0003 self-contained for
    # operators who need to apply it to a partially migrated DB.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'travel_ops_app_user') THEN
                CREATE ROLE travel_ops_app_user NOLOGIN NOINHERIT;
                GRANT travel_ops_app_user TO CURRENT_USER;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA public TO travel_ops_app_user;
                GRANT USAGE, SELECT, UPDATE
                    ON ALL SEQUENCES IN SCHEMA public TO travel_ops_app_user;
            END IF;
        END $$;
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON audit_log TO travel_ops_app_user")


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
        op.execute("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")
    op.drop_table("audit_log")
