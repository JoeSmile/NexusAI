"""Task 49 — llm_api_keys allowed_models + owner_user_id columns."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "020_llm_key_models"
down_revision = "019_offerings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_api_keys",
        sa.Column("allowed_models", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "llm_api_keys",
        sa.Column("owner_user_id", sa.String(length=64), nullable=True),
    )
    # Partial unique: one active tenant-level key per tenant+provider (optional; enforce in app if unique index is awkward)


def downgrade() -> None:
    op.drop_column("llm_api_keys", "owner_user_id")
    op.drop_column("llm_api_keys", "allowed_models")
