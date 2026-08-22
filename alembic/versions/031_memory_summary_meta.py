"""Task 61 slice 2 — structured summary_meta on memory tables."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "031_memory_summary_meta"
down_revision = "030_audit_text_encryption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cold_memories",
        sa.Column("summary_meta", JSONB(), nullable=True),
    )
    op.add_column(
        "user_memories",
        sa.Column("summary_meta", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_memories", "summary_meta")
    op.drop_column("cold_memories", "summary_meta")
