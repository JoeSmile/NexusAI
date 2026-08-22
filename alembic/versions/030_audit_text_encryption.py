"""Task 59 S4 — encrypted audit text columns."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "030_audit_text_encryption"
down_revision = "029_multimodal_modality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("input_text_enc", sa.Text(), nullable=True))
    op.add_column("audit_logs", sa.Column("output_text_enc", sa.Text(), nullable=True))
    op.add_column(
        "audit_logs",
        sa.Column("text_enc_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("audit_logs", "text_enc_version")
    op.drop_column("audit_logs", "output_text_enc")
    op.drop_column("audit_logs", "input_text_enc")
