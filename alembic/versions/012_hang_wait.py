"""Wave E — hang tables + workflow.request_policy

Revision ID: 012_hang_wait
Revises: 011_workflow_runs
Create Date: 2026-08-14

1A: alembic + ORM（与 C/D 一致）
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "012_hang_wait"
down_revision = "011_workflow_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("request_policy", JSONB(), nullable=True),
    )

    op.create_table(
        "permission_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("applicant_user_id", sa.String(length=64), nullable=False),
        sa.Column("needed_perm", sa.String(length=128), nullable=False),
        sa.Column("org_unit_id", sa.String(length=36), nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("requestable_mode", sa.String(length=16), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_permission_requests_tenant", "permission_requests", ["tenant_id"])
    op.create_index("ix_permission_requests_run", "permission_requests", ["run_id"])
    op.create_index(
        "ix_permission_requests_pending_unique",
        "permission_requests",
        ["run_id", "node_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "workflow_grants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="recurring"),
        sa.Column("applicant_user_id", sa.String(length=64), nullable=False),
        sa.Column("caps", JSONB(), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="approval"),
        sa.UniqueConstraint("request_id", name="uq_workflow_grants_request_id"),
    )
    op.create_index("ix_workflow_grants_tenant_wf", "workflow_grants", ["tenant_id", "workflow_id"])
    op.create_index(
        "ix_workflow_grants_applicant",
        "workflow_grants",
        ["tenant_id", "applicant_user_id", "workflow_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_grants_applicant", table_name="workflow_grants")
    op.drop_index("ix_workflow_grants_tenant_wf", table_name="workflow_grants")
    op.drop_table("workflow_grants")
    op.drop_index("ix_permission_requests_pending_unique", table_name="permission_requests")
    op.drop_index("ix_permission_requests_run", table_name="permission_requests")
    op.drop_index("ix_permission_requests_tenant", table_name="permission_requests")
    op.drop_table("permission_requests")
    op.drop_column("workflows", "request_policy")
