"""add agent_run_id FK to review_case

Revision ID: 0007_review_case_agent_run_fk
Revises: 0006_task_run
Create Date: 2026-04-24 10:00:00.000000

P5.4: replace the opaque ``payload_json.agent_run_id`` JSON field with
an explicit FK column so HITL resume can JOIN instead of Python-filter.

Backfills from ``payload_json`` for existing rows so the transition
doesn't leave cases dangling. The old JSON field remains written during
a deprecation window.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_review_case_agent_run_fk"
down_revision: str | Sequence[str] | None = "0006_task_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column(
        "review_case",
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_review_case_agent_run_id",
        "review_case",
        ["agent_run_id"],
    )

    # Named FK so downgrade can target it. Separate from the column add
    # because SQLite (used in tests) doesn't support inline FK add via
    # ALTER without batch mode; we only emit the real constraint on PG.
    if _is_postgres():
        op.create_foreign_key(
            "fk_review_case_agent_run_id",
            "review_case",
            "agent_run",
            ["agent_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Backfill: copy payload_json->>'agent_run_id' into the new column
    # where payload_json has one. PG only (SQLite tests recreate from
    # scratch).
    if _is_postgres():
        op.execute(
            """
            UPDATE review_case
            SET agent_run_id = payload_json->>'agent_run_id'
            WHERE payload_json ? 'agent_run_id'
              AND payload_json->>'agent_run_id' IS NOT NULL
            """
        )


def downgrade() -> None:
    if _is_postgres():
        op.drop_constraint("fk_review_case_agent_run_id", "review_case", type_="foreignkey")
    op.drop_index("ix_review_case_agent_run_id", table_name="review_case")
    op.drop_column("review_case", "agent_run_id")
