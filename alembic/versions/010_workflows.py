"""Wave C — workflows table + capabilities.param_spec

Revision ID: 010_workflows
Revises: 009_rag_org_unit
Create Date: 2026-08-12

C0: capabilities.param_spec JSONB
C2: workflows table (same revision; applied together)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "010_workflows"
down_revision = "009_rag_org_unit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "capabilities",
        sa.Column("param_spec", JSONB(), nullable=True),
    )

    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("org_unit_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("ir_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Text(), nullable=False, server_default="V1.0.0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forked_from_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_workflows_tenant_id", "workflows", ["tenant_id"])
    op.create_index("ix_workflows_org_unit_id", "workflows", ["org_unit_id"])
    op.create_index("ix_workflows_tenant_status", "workflows", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_workflows_tenant_status", table_name="workflows")
    op.drop_index("ix_workflows_org_unit_id", table_name="workflows")
    op.drop_index("ix_workflows_tenant_id", table_name="workflows")
    op.drop_table("workflows")
    op.drop_column("capabilities", "param_spec")
