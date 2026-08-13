"""Wave D — workflow_runs + workflow_run_nodes

Revision ID: 011_workflow_runs
Revises: 010_workflows
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "011_workflow_runs"
down_revision = "010_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("org_unit_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("ir_snapshot", JSONB(), nullable=False),
        sa.Column("workflow_version", sa.Text(), nullable=False, server_default="V1.0.0"),
        sa.Column("workflow_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_ref", JSONB(), nullable=True),
        sa.Column("parent_run_id", sa.String(length=36), nullable=True),
        sa.Column("acting_user_id", sa.String(length=64), nullable=False),
        sa.Column("credential_kind", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workflow_runs_tenant_created", "workflow_runs", ["tenant_id", "created_at"])
    op.create_index("ix_workflow_runs_tenant_status", "workflow_runs", ["tenant_id", "status"])
    op.create_index("ix_workflow_runs_org_unit_id", "workflow_runs", ["org_unit_id"])
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])

    op.create_table(
        "workflow_run_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("output_json", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_run_nodes_idempotency"),
    )
    op.create_index("ix_workflow_run_nodes_run_id", "workflow_run_nodes", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_run_nodes_run_id", table_name="workflow_run_nodes")
    op.drop_table("workflow_run_nodes")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_org_unit_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_tenant_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_tenant_created", table_name="workflow_runs")
    op.drop_table("workflow_runs")
