"""mcp_servers table for admin console MCP CRUD (Task 67 slice 2)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "033_mcp_servers"
down_revision = "032_audit_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="*"),
        sa.Column("transport", sa.Text(), nullable=False, server_default="stdio"),
        sa.Column("command", sa.Text(), nullable=False, server_default=""),
        sa.Column("args", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("env", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("headers_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "allow_pass_user_context",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("timeout_s", sa.Float(), nullable=False, server_default="30"),
        sa.Column("last_probe", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_mcp_servers_tenant", "mcp_servers", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_mcp_servers_tenant", table_name="mcp_servers")
    op.drop_table("mcp_servers")
