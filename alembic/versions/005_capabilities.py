"""capabilities table for Capability Registry (Task 30.02)

Revision ID: 005_capabilities
Revises: 004_key_failover
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "005_capabilities"
down_revision = "004_key_failover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capabilities",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default="*",
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("spec", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="enabled",
        ),
        sa.Column(
            "cost_model",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("permission", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_capabilities_tenant", "capabilities", ["tenant_id"])
    op.create_index("idx_capabilities_kind", "capabilities", ["kind"])


def downgrade() -> None:
    op.drop_index("idx_capabilities_kind", table_name="capabilities")
    op.drop_index("idx_capabilities_tenant", table_name="capabilities")
    op.drop_table("capabilities")
