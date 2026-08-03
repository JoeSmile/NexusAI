"""extend users table for account/password login (Task 38)

在 001 已建的 users(user_id/username)基础上补充账号体系列:
password_hash(bcrypt)/display_name/tenant_id/role,并给 username 加唯一索引。

Revision ID: 006_users
Revises: 005_capabilities
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "006_users"
down_revision = "005_capabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("users", sa.Column("display_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("tenant_id", sa.String(length=50), nullable=False, server_default="acme"))
    op.add_column("users", sa.Column("role", sa.String(length=32), nullable=False, server_default="user"))
    # username 变为唯一登录名(Postgres 唯一索引允许多个 NULL,存量行不受影响)
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "role")
    op.drop_column("users", "tenant_id")
    op.drop_column("users", "display_name")
    op.drop_column("users", "password_hash")
