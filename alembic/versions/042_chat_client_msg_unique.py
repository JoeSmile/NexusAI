"""Partial unique on chat_messages (tenant_id, client_message_id, role) (Task 84 S2)

Revision ID: 042_chat_client_msg_unique
Revises: 041_knowledge_documents
"""

from __future__ import annotations

from alembic import op

revision = "042_chat_client_msg_unique"
down_revision = "041_knowledge_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM chat_messages a
        USING chat_messages b
        WHERE a.client_message_id IS NOT NULL
          AND b.client_message_id IS NOT NULL
          AND a.tenant_id = b.tenant_id
          AND a.client_message_id = b.client_message_id
          AND a.role = b.role
          AND a.id > b.id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_tenant_client_role
        ON chat_messages (tenant_id, client_message_id, role)
        WHERE client_message_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_chat_messages_tenant_client_role")
