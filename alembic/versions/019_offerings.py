"""Task 45 — offerings + content_artifacts tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "019_offerings"
down_revision = "018_audit_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offerings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="*"),
        sa.Column("dept", sa.String(length=64), nullable=False, server_default="content_growth"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="placeholder"),
        sa.Column("target_kind", sa.String(length=32), nullable=False, server_default="capability"),
        sa.Column("target_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_offerings_tenant_id", "offerings", ["tenant_id"])
    op.create_index("ix_offerings_dept", "offerings", ["dept"])

    op.create_table(
        "content_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="hotspot"),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("body", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("creator_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_content_artifacts_tenant_kind_created",
        "content_artifacts",
        ["tenant_id", "kind", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_artifacts_tenant_kind_created", table_name="content_artifacts")
    op.drop_table("content_artifacts")
    op.drop_index("ix_offerings_dept", table_name="offerings")
    op.drop_index("ix_offerings_tenant_id", table_name="offerings")
    op.drop_table("offerings")
