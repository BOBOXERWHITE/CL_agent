"""add traffic_percent column to prompt_template

Revision ID: 0009_prompt_traffic_percent
Revises: 0008_token_usage_daily
Create Date: 2026-04-25 09:00:00.000000

P6.1: extend prompt_template with the ``traffic_percent`` column so A/B
candidate versions can carry a rollout percentage. Existing rows keep
status=draft|active; the new column defaults to 0 (no traffic) which
is safe for both — active versions don't use traffic_percent, and
draft versions don't get selected either way.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_prompt_traffic_percent"
down_revision: str | Sequence[str] | None = "0008_token_usage_daily"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_template",
        sa.Column(
            "traffic_percent",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("prompt_template", "traffic_percent")
