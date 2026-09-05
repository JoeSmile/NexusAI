"""Index user_memories (tenant_id, user_id, updated_at DESC) for warm SQL (S1c).

Revision ID: 043_user_memories_tid_uid_updated
Revises: 042_chat_client_msg_unique
"""

from __future__ import annotations

from alembic import op

revision = "043_user_memories_tid_uid_updated"
down_revision = "042_chat_client_msg_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_memories_tid_uid_updated
        ON user_memories (tenant_id, user_id, updated_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_memories_tid_uid_updated")
