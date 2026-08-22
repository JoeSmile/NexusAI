"""Task 55 slice 1 — append-only usage_records (billing meter)."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "026_usage_records"
down_revision = "025_audit_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        sa.Column("credential_kind", sa.String(length=32), nullable=False, server_default="company"),
        sa.Column("key_id", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(precision=14, scale=6), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        sa.Column("billing_month", sa.String(length=7), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_usage_records_idempotency"),
    )
    op.create_index(
        "ix_usage_records_tenant_month",
        "usage_records",
        ["tenant_id", "billing_month"],
        unique=False,
    )
    op.create_index(
        "ix_usage_records_tenant_created",
        "usage_records",
        ["tenant_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_tenant_created", table_name="usage_records")
    op.drop_index("ix_usage_records_tenant_month", table_name="usage_records")
    op.drop_table("usage_records")
