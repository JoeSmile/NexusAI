"""llm_api_keys cooldown columns for key failover

Revision ID: 004_key_failover
Revises: 003
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_key_failover"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_api_keys",
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "llm_api_keys",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_api_keys", "consecutive_failures")
    op.drop_column("llm_api_keys", "last_failed_at")
