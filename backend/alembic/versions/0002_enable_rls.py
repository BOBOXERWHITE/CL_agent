"""enable PostgreSQL row-level security on tenant-scoped tables

Revision ID: 0002_enable_rls
Revises: 0001_baseline
Create Date: 2026-04-20 12:00:00.000000

Enables RLS + a tenant-isolation policy on every table that carries a
``tenant_id`` column. The policy reads the per-transaction GUC
``app.tenant_id``; ``app.session.py`` sets it via ``SET LOCAL`` at the start
of each request transaction.

Sentinel value ``__bypass__`` allows backend jobs (Celery workers,
ingestion, eval runner) to operate across tenants without granting them a
``BYPASSRLS`` role. Production deployments that want stricter isolation can
swap to a real ``CREATE ROLE service_role BYPASSRLS`` and remove the
sentinel from the policy.

Tables covered (direct tenant_id column):
    agent_run, chat_session, knowledge_document, knowledge_chunk,
    rag_recall_log, runtime_log, review_case

Tables NOT covered (no direct tenant_id; rely on FK + parent's RLS):
    chat_message, tool_call_log

This migration is a no-op on SQLite (which has no RLS), so the unit test
suite continues to pass without change. The PG integration suite verifies
the policies actually block cross-tenant reads.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_enable_rls"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TENANT_TABLES: tuple[str, ...] = (
    "agent_run",
    "chat_session",
    "knowledge_document",
    "knowledge_chunk",
    "rag_recall_log",
    "runtime_log",
    "review_case",
)


_POLICY_NAME = "tenant_isolation"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # SQLite (test suite) and other dialects: RLS is a PG feature, no-op.
        return

    # Create a non-superuser role that the application impersonates per-request
    # via ``SET LOCAL ROLE``. This is the linchpin of the policy: PostgreSQL
    # superusers and BYPASSRLS roles always skip RLS, so just enabling the
    # policy is not enough -- queries must run as a role that does *not* have
    # those attributes. We create the role NOINHERIT NOLOGIN; it is meant to
    # be assumed via SET ROLE, never logged into directly.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'travel_ops_app_user') THEN
                CREATE ROLE travel_ops_app_user NOLOGIN NOINHERIT;
            END IF;
        END $$;
        """
    )
    # Allow the connecting role (whatever it is in dev/test/prod) to assume
    # the app role. In a hardened production deploy, the connecting role
    # itself should have no rights and only inherit via SET ROLE, but here we
    # keep the connecting role as the schema owner for migration ergonomics.
    op.execute("GRANT travel_ops_app_user TO CURRENT_USER")

    # Grant the app role enough to do its job: read/write the tenant tables
    # plus their child tables (chat_message, tool_call_log) and sequences.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO travel_ops_app_user"
    )
    op.execute(
        "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO travel_ops_app_user"
    )

    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE so the table owner is also subject to RLS. Mostly a defence-
        # in-depth: the application connects as the schema owner in many
        # deployments, and we want them to honour the policy too.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        if table == "runtime_log":
            # runtime_log.tenant_id is nullable (unauth'd requests like
            # /health log NULL). Allow NULL rows only under the bypass
            # sentinel so admins can audit them, otherwise tenants see
            # only their own log lines.
            op.execute(
                f"""
                CREATE POLICY {_POLICY_NAME} ON {table}
                USING (
                    tenant_id = current_setting('app.tenant_id', true)
                    OR current_setting('app.tenant_id', true) = '__bypass__'
                )
                """
            )
        else:
            op.execute(
                f"""
                CREATE POLICY {_POLICY_NAME} ON {table}
                USING (
                    tenant_id = current_setting('app.tenant_id', true)
                    OR current_setting('app.tenant_id', true) = '__bypass__'
                )
                """
            )


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM travel_ops_app_user")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM travel_ops_app_user")
    op.execute("DROP ROLE IF EXISTS travel_ops_app_user")
