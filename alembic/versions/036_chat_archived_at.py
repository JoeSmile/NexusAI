"""chat_messages.archived_at (Task 78.1) — NULL means live L0."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "036_chat_archived_at"
down_revision = "035_attachment_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "archived_at")
