"""Database engine, session factory, and schema bootstrap.

SQLite (tests) uses ``Base.metadata.create_all`` for speed. PostgreSQL uses
Alembic via :func:`ensure_schema` so schema evolution is versioned.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base

# Sentinel value that the RLS policy in alembic 0002 recognises as "skip the
# tenant filter for this transaction". Used by Celery workers, ingestion
# pipelines, eval runners, and Phase 0 lifespan bootstrap -- code paths that
# legitimately operate across tenants.
RLS_BYPASS_SENTINEL = "__bypass__"

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_configured_database_url: str | None = None
_initialized_urls: set[str] = set()


def _build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return create_engine(database_url, future=True)


def get_engine() -> Engine:
    global _engine, _session_factory, _configured_database_url

    settings = get_settings()
    if _engine is None or _configured_database_url != settings.database_url:
        _engine = _build_engine(settings.database_url)
        _session_factory = sessionmaker(
            bind=_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        # Rebinding to a new URL means the prior init flag no longer applies.
        if _configured_database_url is not None:
            _initialized_urls.discard(_configured_database_url)
        _configured_database_url = settings.database_url

    return _engine


def SessionLocal() -> Session:
    """Return a new session bound to the currently configured engine.

    ``get_engine()`` refreshes ``_session_factory`` whenever the configured
    ``DATABASE_URL`` changes, so callers always end up bound to the active
    engine. This replaces the previous ``_SessionLocalProxy`` with its
    drift-detection assertion (P0.5): the callable interface is unchanged,
    but the weird proxy class is gone.
    """
    get_engine()
    assert _session_factory is not None
    return _session_factory()


def _import_all_models() -> None:
    """Ensure every model is registered on ``Base.metadata``.

    Importing the submodule has the side effect of binding its ``Mapped`` class
    into the declarative registry. Listing them here avoids a hidden ``*``
    import and keeps mypy / ruff happy.
    """
    from app.db.models import (  # noqa: F401
        agent,
        agent_event,
        agent_memory,
        audit_log,
        conversation,
        eval,
        knowledge,
        prompt_feedback,
        prompt_selection_log,
        prompt_template,
        rag_recall_log,
        rule,
        runtime_log,
        system_setting,
        task_run,
        token_usage,
    )


def _run_alembic_upgrade(database_url: str) -> None:
    """Invoke ``alembic upgrade head`` programmatically.

    Alembic is imported lazily so that environments without alembic installed
    (for example, a stripped-down inference container) can still import this
    module.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not ini_path.exists():
        raise RuntimeError(f"alembic.ini not found at {ini_path}")

    alembic_cfg = AlembicConfig(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(ini_path.parent / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_cfg, "head")


def ensure_schema() -> None:
    """Make sure the database schema matches the current models.

    - For SQLite: run ``create_all`` (fast, used by the test suite).
    - For PostgreSQL (and other real RDBMS): run ``alembic upgrade head``.
      If the database already contains tables from the legacy ``create_all``
      path, stamp it to baseline first so that ``upgrade`` is a no-op.
    """
    _import_all_models()
    engine = get_engine()
    settings = get_settings()

    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        return

    inspector = inspect(engine)
    has_alembic_table = inspector.has_table("alembic_version")
    has_domain_tables = inspector.has_table("chat_sessions")

    if has_domain_tables and not has_alembic_table:
        # Legacy DB predates alembic. Stamp to baseline so subsequent
        # upgrades are incremental. We still need to import alembic lazily.
        from alembic import command
        from alembic.config import Config as AlembicConfig

        ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"
        alembic_cfg = AlembicConfig(str(ini_path))
        alembic_cfg.set_main_option("script_location", str(ini_path.parent / "alembic"))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        command.stamp(alembic_cfg, "0001_baseline")
        logger.info(
            "alembic_stamped_baseline",
            extra={"database": _safe_database_identifier(settings.database_url)},
        )

    _run_alembic_upgrade(settings.database_url)
    logger.info(
        "alembic_upgrade_head_completed",
        extra={"database": _safe_database_identifier(settings.database_url)},
    )


def _safe_database_identifier(database_url: str) -> str:
    """Strip credentials from a DB URL for logging."""
    if "@" in database_url:
        return database_url.rsplit("@", 1)[-1]
    return database_url


def init_db() -> None:
    """Idempotent schema bootstrap.

    Safe to call repeatedly; only the first call per (process, database_url)
    actually runs ``ensure_schema``. This keeps non-HTTP callers (Celery
    workers, ad-hoc scripts, tests that import a service directly) working
    without re-running alembic on every call.

    FastAPI routes should no longer call this function — the app lifespan
    runs it once at startup. Keeping a per-URL cache means a stray call is
    cheap (~one dict lookup).
    """
    settings = get_settings()
    if settings.database_url in _initialized_urls:
        return
    ensure_schema()
    _initialized_urls.add(settings.database_url)


def _is_postgres() -> bool:
    return not get_settings().database_url.startswith("sqlite")


def _apply_tenant_scope(session: Session, tenant_id: str | None) -> None:
    """Demote to non-superuser role + SET LOCAL app.tenant_id for RLS.

    Two settings are applied per-transaction:

    1. ``SET LOCAL ROLE travel_ops_app_user`` -- demote from the connecting
       role (which may be a superuser, especially in test containers) to the
       non-superuser app role. Superusers always bypass RLS, so this step is
       what makes the policy actually enforce.
    2. ``SET LOCAL app.tenant_id = '<id>'`` -- set the GUC the policy reads.

    Both are reset automatically when the transaction commits or rolls back.
    No-op on SQLite (no RLS support). Caller must guarantee this runs inside
    a transaction (SQLAlchemy starts one on first execute() with autocommit
    off, which is our default).
    """
    if not _is_postgres():
        return
    value = tenant_id or ""
    # SET LOCAL parameter binding doesn't work for GUC names, so the value
    # is bound separately. We sanitise with a length check + character class
    # because PostgreSQL's parser would reject a quote-bearing value anyway,
    # but defence in depth is cheap.
    if any(ch in value for ch in ("'", '"', "\\", ";")):
        raise ValueError(f"unsafe tenant_id for SET LOCAL: {value!r}")
    session.execute(text("SET LOCAL ROLE travel_ops_app_user"))
    session.execute(text(f"SET LOCAL app.tenant_id = '{value}'"))


def get_session(request: Request) -> Generator[Session]:
    """FastAPI dependency: yield a session scoped to the caller's tenant.

    FastAPI auto-injects ``Request``, so route signatures stay unchanged:
    ``session: Session = Depends(get_session)`` still works.

    Behaviour matrix:

    +-------------------------------+--------------------------------------+
    | request.state.tenant_id       | Action                               |
    +===============================+======================================+
    | real tenant id (JWT mode)     | SET LOCAL ROLE app_user + GUC =      |
    |                               | tenant_id. RLS enforces.             |
    +-------------------------------+--------------------------------------+
    | "default-tenant" placeholder  | Bypass RLS (sentinel). The static-   |
    | (static-token-mode default)   | token claim is not a real tenant     |
    |                               | boundary; legacy tests that send a   |
    |                               | body tenant_id different from the    |
    |                               | claim need the writes to succeed.    |
    |                               | Production cannot reach this branch  |
    |                               | because _validate_production_security|
    |                               | forces JWT_ENABLED=true.             |
    +-------------------------------+--------------------------------------+
    | None (no auth chain ran)      | Bypass for /health and similar       |
    |                               | unauthenticated routes that may      |
    |                               | still touch the DB. They should      |
    |                               | not hit tenant tables.               |
    +-------------------------------+--------------------------------------+

    SQLite test path: every branch is a no-op; existing tests work.
    """
    session = SessionLocal()
    try:
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id and tenant_id not in ("default-tenant", "default-customer"):
            _apply_tenant_scope(session, tenant_id)
        elif _is_postgres():
            session.execute(text(f"SET LOCAL app.tenant_id = '{RLS_BYPASS_SENTINEL}'"))
        yield session
    finally:
        session.close()


@contextmanager
def bypass_rls_session() -> Iterator[Session]:
    """Context manager for non-HTTP callers that legitimately span tenants.

    Use this in Celery workers, the ingestion pipeline, the eval runner,
    and lifespan bootstrap -- anywhere there is no per-request tenant. The
    PG row-level security policy recognises ``__bypass__`` as "show every
    row".

    Production hardening: replace this sentinel with a dedicated PG service
    role (``CREATE ROLE service_role BYPASSRLS``) so a bug that omits the
    bypass call cannot accidentally leak data. The sentinel approach is
    chosen here for migration simplicity.
    """
    session = SessionLocal()
    try:
        if _is_postgres():
            session.execute(text(f"SET LOCAL app.tenant_id = '{RLS_BYPASS_SENTINEL}'"))
        yield session
    finally:
        session.close()


@contextmanager
def scoped_session(tenant_id: str | None) -> Iterator[Session]:
    """Imperative variant of :func:`get_session` for non-FastAPI callers.

    Useful in scripts and tests that need to issue queries as a specific
    tenant. Pass ``tenant_id=None`` to fail closed -- the role is still
    demoted to ``travel_ops_app_user`` and the GUC is set to an empty string,
    so RLS sees zero rows. Use :func:`bypass_rls_session` for legitimate
    cross-tenant work.
    """
    session = SessionLocal()
    try:
        # Always apply the scope (even with empty tenant_id) so the
        # connection demotes to the non-superuser role; otherwise RLS
        # would be bypassed and the unscoped fallback would leak data.
        _apply_tenant_scope(session, tenant_id or "")
        yield session
    finally:
        session.close()
