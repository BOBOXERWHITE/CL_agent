"""Alembic migration environment for Travel Ops Copilot.

This module loads the database URL from app settings (env vars), not from
alembic.ini, so there is a single source of truth for configuration.

All SQLAlchemy models must be imported before `target_metadata` is bound
so that autogenerate can diff against the full schema.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import Base and all models so Base.metadata knows every table.
from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (  # noqa: F401  (side-effect imports to register tables)
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

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override alembic.ini placeholder with the real app setting.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to) -> bool:
    """Skip the alembic_version table itself from autogenerate diffs."""
    return not (type_ == "table" and name == "alembic_version")


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emits raw SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
