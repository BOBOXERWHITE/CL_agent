"""baseline schema (all 11 tables from SQLAlchemy models)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-07 12:00:00.000000

This is the transition baseline. It uses Base.metadata.create_all() so that a
fresh database becomes fully initialised by running `alembic upgrade head`.

For databases that already contain the schema (legacy dev/prod created via the
old init_db() path), run `alembic stamp 0001_baseline` once instead of
`upgrade`. Future changes should be generated with `alembic revision
--autogenerate -m "<message>"` and reviewed before applying.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.db.base import Base
from app.db.models import (  # noqa: F401  (register all tables)
    agent,
    conversation,
    eval,
    knowledge,
    prompt_template,
    rag_recall_log,
    rule,
    runtime_log,
    system_setting,
)

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables that existed at the time this baseline was generated. Later
# revisions (0003 audit_log, ...) MUST create their own tables in their own
# migration file -- don't add new names here. Without this explicit list
# ``Base.metadata.create_all`` would silently include every model later
# imported into the metadata, which then collides with the explicit
# ``op.create_table`` in the follow-on migration.
_BASELINE_TABLE_NAMES: tuple[str, ...] = (
    "agent_run",
    "tool_call_log",
    "chat_session",
    "chat_message",
    "knowledge_document",
    "knowledge_chunk",
    "eval_dataset",
    "eval_run",
    "prompt_template",
    "rag_recall_log",
    "policy_rule",
    "review_case",
    "runtime_log",
    "system_setting",
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in _BASELINE_TABLE_NAMES]
    Base.metadata.create_all(bind=bind, tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in _BASELINE_TABLE_NAMES]
    Base.metadata.drop_all(bind=bind, tables=tables)
