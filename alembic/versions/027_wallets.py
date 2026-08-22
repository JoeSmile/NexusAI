"""Task 55 slice 2 — prepaid wallets + append-only transactions."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "027_wallets"
down_revision = "026_usage_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("balance", sa.Numeric(precision=14, scale=4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_wallets_tenant_id"),
    )
    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("reference_no", sa.String(length=128), nullable=True),
        sa.Column("operator", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wallet_tx_tenant_created",
        "wallet_transactions",
        ["tenant_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_tx_tenant_created", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_table("wallets")
