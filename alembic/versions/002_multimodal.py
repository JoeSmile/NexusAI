"""add knowledge_chunks.source_type for multimodal RAG

Revision ID: 002_multimodal
Revises: 001_initial_schema
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_multimodal"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column("source_type", sa.String(length=32), server_default="text", nullable=False),
    )
    op.create_index("ix_knowledge_chunks_source_type", "knowledge_chunks", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_source_type", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "source_type")
