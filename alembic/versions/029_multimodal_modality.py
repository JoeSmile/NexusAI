"""Task 58 slice 1 — modality + image_hash on audit/usage."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "029_multimodal_modality"
down_revision = "028_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("modality", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("image_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "usage_records",
        sa.Column("modality", sa.String(length=32), nullable=True, server_default="text"),
    )
    op.add_column(
        "usage_records",
        sa.Column("image_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("usage_records", "image_hash")
    op.drop_column("usage_records", "modality")
    op.drop_column("audit_logs", "image_hash")
    op.drop_column("audit_logs", "modality")
