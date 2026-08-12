"""Wave B — knowledge_chunks.org_unit_id for RAG OrgScope

Revision ID: 009_rag_org_unit
Revises: 008_org_b
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009_rag_org_unit"
down_revision = "008_org_b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column("org_unit_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_knowledge_chunks_org_unit_id",
        "knowledge_chunks",
        ["org_unit_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_org_unit_id", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "org_unit_id")
