"""Wave B — org schema migration: org_units + org_memberships

Revision ID: 008_org_b
Revises: 007_credential_scaffold
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008_org_b"
down_revision = "007_credential_scaffold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_units",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["org_units.id"]),
    )
    op.create_index("ix_org_units_tenant_path", "org_units", ["tenant_id", "path"])
    op.create_index("ix_org_units_tenant_id", "org_units", ["tenant_id"])

    op.create_table(
        "org_memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("org_unit_id", sa.String(length=36), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("business_roles", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_unit_id"], ["org_units.id"]),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "org_unit_id", name="uq_org_membership_tenant_user_unit"
        ),
    )
    op.create_index(
        "ix_org_memberships_tenant_user",
        "org_memberships",
        ["tenant_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_org_memberships_tenant_user", table_name="org_memberships")
    op.drop_table("org_memberships")
    op.drop_index("ix_org_units_tenant_id", table_name="org_units")
    op.drop_index("ix_org_units_tenant_path", table_name="org_units")
    op.drop_table("org_units")
