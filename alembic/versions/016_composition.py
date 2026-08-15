"""Task 40.81 — composition columns on workflow_runs

Revision ID: 016_composition
Revises: 015_skill_assets
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "016_composition"
down_revision = "015_skill_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("parent_node_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column(
            "composition_depth",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("run_inputs", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_workflow_runs_parent_run_id",
        "workflow_runs",
        ["parent_run_id"],
    )
    op.add_column(
        "workflows",
        sa.Column("intent_tags", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflows", "intent_tags")
    op.drop_index("ix_workflow_runs_parent_run_id", table_name="workflow_runs")
    op.drop_column("workflow_runs", "run_inputs")
    op.drop_column("workflow_runs", "composition_depth")
    op.drop_column("workflow_runs", "parent_node_id")
