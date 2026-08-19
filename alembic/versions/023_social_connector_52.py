"""Task 52 S2 — social_* tables (accounts/contents/tasks/templates/results/usage)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "023_social_connector_52"
down_revision = "022_user_feedback_47b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "social_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("account_key", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("nickname", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("follower_count", sa.BigInteger(), nullable=True),
        sa.Column("total_favorited", sa.BigInteger(), nullable=True),
        sa.Column("content_count", sa.BigInteger(), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_json", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("platform", "account_key", name="uq_social_accounts_platform_key"),
    )

    op.create_table(
        "social_contents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("social_accounts.id"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False, server_default="video"),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_source", sa.Text(), nullable=False, server_default="desc"),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("share_count", sa.Integer(), nullable=True),
        sa.Column("collect_count", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_json", JSONB(), nullable=True),
        sa.UniqueConstraint(
            "platform", "external_id", name="uq_social_contents_platform_external"
        ),
    )
    op.create_index("ix_social_contents_account_id", "social_contents", ["account_id"])

    op.create_table(
        "social_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("social_accounts.id"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_social_tasks_tenant_user", "social_tasks", ["tenant_id", "user_id"])
    op.create_index("ix_social_tasks_status", "social_tasks", ["status"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_social_tasks_one_active
        ON social_tasks (tenant_id, user_id)
        WHERE status IN ('pending', 'running')
        """
    )

    # templates before results (FK)
    op.create_table(
        "social_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("template_type", sa.Text(), nullable=True),
        sa.Column("structure_json", JSONB(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "platform",
            "template_key",
            name="uq_social_templates_tenant_platform_key",
        ),
    )
    op.create_index(
        "ix_social_templates_tenant_platform",
        "social_templates",
        ["tenant_id", "platform"],
    )

    op.create_table(
        "social_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("social_tasks.id"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.BigInteger(),
            sa.ForeignKey("social_contents.id"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.BigInteger(),
            sa.ForeignKey("social_templates.id"),
            nullable=True,
        ),
        sa.Column("structure_json", JSONB(), nullable=True),
        sa.Column("replica_json", JSONB(), nullable=True),
        sa.UniqueConstraint("task_id", "content_id", name="uq_social_results_task_content"),
    )
    op.create_index("ix_social_results_task_id", "social_results", ["task_id"])

    op.create_table(
        "social_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("price_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_social_usage_created_at", "social_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_social_usage_created_at", table_name="social_usage")
    op.drop_table("social_usage")
    op.drop_index("ix_social_results_task_id", table_name="social_results")
    op.drop_table("social_results")
    op.drop_index("ix_social_templates_tenant_platform", table_name="social_templates")
    op.drop_table("social_templates")
    op.execute("DROP INDEX IF EXISTS uq_social_tasks_one_active")
    op.drop_index("ix_social_tasks_status", table_name="social_tasks")
    op.drop_index("ix_social_tasks_tenant_user", table_name="social_tasks")
    op.drop_table("social_tasks")
    op.drop_index("ix_social_contents_account_id", table_name="social_contents")
    op.drop_table("social_contents")
    op.drop_table("social_accounts")
