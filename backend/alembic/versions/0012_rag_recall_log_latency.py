"""add latency_ms + confidence columns to rag_recall_log

Revision ID: 0012_rag_recall_log_latency
Revises: 0011_prompt_feedback
Create Date: 2026-04-26 09:00:00.000000

P7.3: materialise request-level latency and answer confidence into
their own columns so ``/api/prompts/{id}/stats`` and
``/api/health/slo`` can compute real numbers via ``AVG()`` /
percentile queries instead of falling back to null.

Existing rows get NULL; the chat route only back-fills going forward.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_rag_recall_log_latency"
down_revision: str | Sequence[str] | None = "0011_prompt_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rag_recall_log",
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "rag_recall_log",
        sa.Column("confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rag_recall_log", "confidence")
    op.drop_column("rag_recall_log", "latency_ms")
