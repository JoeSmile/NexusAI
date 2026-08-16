"""I-1(评审 08-15) — audit_logs dedupe_key 唯一列。

worker 异步记忆审计去重：重放/重复投递时唯一约束拦截重复审计行。
"""

from alembic import op
import sqlalchemy as sa

revision = "018_audit_dedupe"
down_revision = "017_scheduled_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("dedupe_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_audit_logs_dedupe",
        "audit_logs",
        ["tenant_id", "dedupe_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_dedupe", table_name="audit_logs")
    op.drop_column("audit_logs", "dedupe_key")
