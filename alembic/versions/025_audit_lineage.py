"""Task 56 — audit_logs 血缘字段 parent_trace_id / tool_use_id / decision_explain."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "025_audit_lineage"
down_revision = "024_social_follows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("parent_trace_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("tool_use_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("decision_explain", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_audit_logs_parent_trace",
        "audit_logs",
        ["tenant_id", "parent_trace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_parent_trace", table_name="audit_logs")
    op.drop_column("audit_logs", "decision_explain")
    op.drop_column("audit_logs", "tool_use_id")
    op.drop_column("audit_logs", "parent_trace_id")
