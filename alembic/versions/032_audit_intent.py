"""Task 65 slice 0 — intent telemetry columns on audit_logs."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "032_audit_intent"
down_revision = "031_memory_summary_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("intent_predicted", sa.String(32), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("intent_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("intent_source", sa.String(16), nullable=True),
    )
    op.create_index(
        "ix_audit_intent_tenant_time",
        "audit_logs",
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("intent_predicted IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_audit_intent_tenant_time", table_name="audit_logs")
    op.drop_column("audit_logs", "intent_source")
    op.drop_column("audit_logs", "intent_confidence")
    op.drop_column("audit_logs", "intent_predicted")
