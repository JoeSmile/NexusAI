"""Task 43 — skill_assets table

Revision ID: 015_skill_assets
Revises: 014_notifications
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "015_skill_assets"
down_revision = "014_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cot_template", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "ir_skeleton",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "visibility",
            sa.String(length=32),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "usage_stats",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_skill_assets_tenant", "skill_assets", ["tenant_id"])
    op.create_index(
        "ix_skill_assets_published_name",
        "skill_assets",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )


def downgrade() -> None:
    op.drop_index("ix_skill_assets_published_name", table_name="skill_assets")
    op.drop_index("ix_skill_assets_tenant", table_name="skill_assets")
    op.drop_table("skill_assets")
