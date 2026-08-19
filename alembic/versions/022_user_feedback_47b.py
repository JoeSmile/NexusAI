"""47b slice1 — user_feedback tenant_id + client_message_id + U1 partial uniques."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "022_user_feedback_47b"
down_revision = "021_chat_client_message_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_feedback",
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "user_feedback",
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_user_feedback_tenant_id",
        "user_feedback",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_feedback_client_message_id",
        "user_feedback",
        ["client_message_id"],
        unique=False,
    )
    # U1: one reaction row per (tenant, user, client_message_id)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_feedback_reaction_client
        ON user_feedback (tenant_id, user_id, client_message_id)
        WHERE client_message_id IS NOT NULL
          AND feedback_type IN ('helpful', 'irrelevant')
        """
    )
    # one bookmark row per message
    op.execute(
        """
        CREATE UNIQUE INDEX uq_feedback_bookmark_client
        ON user_feedback (tenant_id, user_id, client_message_id)
        WHERE client_message_id IS NOT NULL
          AND feedback_type = 'bookmark'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_feedback_bookmark_client")
    op.execute("DROP INDEX IF EXISTS uq_feedback_reaction_client")
    op.drop_index("ix_user_feedback_client_message_id", table_name="user_feedback")
    op.drop_index("ix_user_feedback_tenant_id", table_name="user_feedback")
    op.drop_column("user_feedback", "client_message_id")
    op.drop_column("user_feedback", "tenant_id")
