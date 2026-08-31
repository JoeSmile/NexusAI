"""attachments + attachment_blocks (Task 76.1) — session memory, no embeddings."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "034_attachments"
down_revision = "005_embed_dim_768"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("uploaded_by", sa.String(length=100), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "media_type",
            sa.String(length=120),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="parsing"),
        sa.Column("storage_path", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_attachments_tenant_session",
        "attachments",
        ["tenant_id", "session_id"],
    )
    op.create_table(
        "attachment_blocks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("attachment_id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("sheet", sa.String(length=200), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["attachments.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "idx_attachment_blocks_attachment",
        "attachment_blocks",
        ["attachment_id", "block_index"],
    )
    op.create_index(
        "idx_attachment_blocks_session",
        "attachment_blocks",
        ["tenant_id", "session_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_attachment_blocks_session", table_name="attachment_blocks")
    op.drop_index("idx_attachment_blocks_attachment", table_name="attachment_blocks")
    op.drop_table("attachment_blocks")
    op.drop_index("idx_attachments_tenant_session", table_name="attachments")
    op.drop_table("attachments")
