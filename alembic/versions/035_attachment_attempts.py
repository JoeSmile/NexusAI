"""attachments.parse_attempts (Task 76.2 worker retries)."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "035_attachment_attempts"
down_revision = "034_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column(
            "parse_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("attachments", "parse_attempts")
