"""47b slice0 — chat_messages.client_message_id for FE UUID hydrate."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "021_chat_client_message_id"
down_revision = "020_llm_key_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_chat_messages_client_message_id",
        "chat_messages",
        ["client_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_tenant_client_msg",
        "chat_messages",
        ["tenant_id", "client_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_tenant_client_msg", table_name="chat_messages")
    op.drop_index("ix_chat_messages_client_message_id", table_name="chat_messages")
    op.drop_column("chat_messages", "client_message_id")
