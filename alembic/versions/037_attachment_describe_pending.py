"""attachments.describe_pending + describe_attempts (Task 76b.0)."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "037_attachment_describe_pending"
down_revision = "036_chat_archived_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column(
            "describe_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "attachments",
        sa.Column(
            "describe_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("attachments", "describe_attempts")
    op.drop_column("attachments", "describe_pending")
