"""Task 44 — notifications inbox table

Revision ID: 014_notifications
Revises: 012_hang_wait
Create Date: 2026-08-14

Task 43 skill_assets 用后续 revision（建议 015_skill_assets → 014），
勿再插空 013（已 applied 的空 revision 无法补 DDL）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "014_notifications"
down_revision = "012_hang_wait"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default="inbox",
        ),
        sa.Column(
            "payload",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_notifications_tenant_user_read",
        "notifications",
        ["tenant_id", "user_id", "read_at"],
    )
    op.create_index(
        "ix_notifications_tenant_user_created",
        "notifications",
        ["tenant_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_tenant_user_created", table_name="notifications")
    op.drop_index("ix_notifications_tenant_user_read", table_name="notifications")
    op.drop_table("notifications")
