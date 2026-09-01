"""content_artifacts owner_user_id + visibility (Task 45b.4)."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "038_content_artifact_visibility"
down_revision = "037_attachment_describe_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_artifacts",
        sa.Column(
            "owner_user_id",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "content_artifacts",
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=False,
            server_default="private",
        ),
    )
    op.create_index(
        "ix_content_artifacts_tenant_owner_kind",
        "content_artifacts",
        ["tenant_id", "owner_user_id", "kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_artifacts_tenant_owner_kind",
        table_name="content_artifacts",
    )
    op.drop_column("content_artifacts", "visibility")
    op.drop_column("content_artifacts", "owner_user_id")
