"""Wave A / W0: credential scaffold columns (nullable, no backfill)

api_keys: credential_type, created_by_user_id
audit_logs: credential_kind, key_id, run_id, node_id

Revision ID: 007_credential_scaffold
Revises: 006_users
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "007_credential_scaffold"
down_revision = "006_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("credential_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column("created_by_user_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("credential_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("key_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("run_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("node_id", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_logs", "node_id")
    op.drop_column("audit_logs", "run_id")
    op.drop_column("audit_logs", "key_id")
    op.drop_column("audit_logs", "credential_kind")
    op.drop_column("api_keys", "created_by_user_id")
    op.drop_column("api_keys", "credential_type")
