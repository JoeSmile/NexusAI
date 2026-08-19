"""Task 52 — tenant follow list for social accounts."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "024_social_follows"
down_revision = "023_social_connector_52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "social_follows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("social_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "account_id", name="uq_social_follows_tenant_account"),
    )
    op.create_index("ix_social_follows_tenant", "social_follows", ["tenant_id"])
    op.execute(
        sa.text(
            """
            INSERT INTO social_follows (tenant_id, account_id)
            SELECT DISTINCT tenant_id, account_id FROM social_tasks
            ON CONFLICT (tenant_id, account_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_social_follows_tenant", table_name="social_follows")
    op.drop_table("social_follows")
