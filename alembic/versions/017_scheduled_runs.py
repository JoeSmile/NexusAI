"""E3.4 — scheduled_runs + grant origin widen

Revision ID: 017_scheduled_runs
Revises: 016_composition
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "017_scheduled_runs"
down_revision = "016_composition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "workflow_grants",
        "origin",
        existing_type=sa.String(length=32),
        type_=sa.String(length=80),
        existing_nullable=False,
    )
    op.create_table(
        "scheduled_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("cron", sa.String(length=64), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("run_inputs", JSONB(), nullable=True),
        # F2(评审 08-15):显式 org_unit_id——cron 触发不依赖 created_by 的 primary org
        # (教育版主播可能未绑 org,resolve_org_scope 会失败→静默 skip);创建时快照 workflow.org
        sa.Column("org_unit_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_scheduled_runs_tenant_id", "scheduled_runs", ["tenant_id"])
    op.create_index("ix_scheduled_runs_workflow_id", "scheduled_runs", ["workflow_id"])
    op.create_index("ix_scheduled_runs_next_run_at", "scheduled_runs", ["next_run_at"])
    op.create_index(
        "ix_scheduled_runs_due",
        "scheduled_runs",
        ["enabled", "next_run_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_runs_due", table_name="scheduled_runs")
    op.drop_index("ix_scheduled_runs_next_run_at", table_name="scheduled_runs")
    op.drop_index("ix_scheduled_runs_workflow_id", table_name="scheduled_runs")
    op.drop_index("ix_scheduled_runs_tenant_id", table_name="scheduled_runs")
    op.drop_table("scheduled_runs")
    op.alter_column(
        "workflow_grants",
        "origin",
        existing_type=sa.String(length=80),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
