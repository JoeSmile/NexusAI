"""Ensure A/B assignment uniqueness (tables already in 001).

Revision ID: 003
Revises: 002
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 表已在 001 创建；补 (user_id, experiment_id) 唯一约束以便幂等分流
    op.create_index(
        "uq_ab_assignment_user_experiment",
        "ab_test_group_assignments",
        ["user_id", "experiment_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ab_assignment_user_experiment",
        table_name="ab_test_group_assignments",
    )
