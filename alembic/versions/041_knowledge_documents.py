"""knowledge_documents + chunks.doc_id/page_no (Task 83)

Revision ID: 041_knowledge_documents
Revises: 040_embed_dim_1024
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "041_knowledge_documents"
down_revision = "040_embed_dim_1024"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _col_names(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _index_names(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table) if i["name"]}


def _fk_names(table: str) -> set[str]:
    names: set[str] = set()
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if fk.get("name"):
            names.add(fk["name"])
        if "doc_id" in (fk.get("constrained_columns") or []):
            names.add("fk_knowledge_chunks_doc_id")
    return names


def upgrade() -> None:
    if "knowledge_documents" not in _table_names():
        op.create_table(
            "knowledge_documents",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=50), nullable=False),
            sa.Column("org_unit_id", sa.String(length=36), nullable=True),
            sa.Column("filename", sa.String(length=256), nullable=False),
            sa.Column("storage_path", sa.Text(), nullable=False, server_default=""),
            sa.Column("file_hash", sa.String(length=64), nullable=False),
            sa.Column("pages", sa.Integer(), nullable=True),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunks_so_far", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
        )
    idx = _index_names("knowledge_documents")
    uniques = {
        u["name"]
        for u in sa.inspect(op.get_bind()).get_unique_constraints("knowledge_documents")
        if u.get("name")
    }
    if "ix_knowledge_documents_tenant_id" not in idx:
        op.create_index(
            "ix_knowledge_documents_tenant_id",
            "knowledge_documents",
            ["tenant_id"],
        )
    if "ix_knowledge_documents_org_unit_id" not in idx:
        op.create_index(
            "ix_knowledge_documents_org_unit_id",
            "knowledge_documents",
            ["org_unit_id"],
        )
    if "ix_knowledge_documents_status" not in idx:
        op.create_index(
            "ix_knowledge_documents_status",
            "knowledge_documents",
            ["status"],
        )
    if "ix_knowledge_documents_tenant_status" not in idx:
        op.create_index(
            "ix_knowledge_documents_tenant_status",
            "knowledge_documents",
            ["tenant_id", "status"],
        )
    if (
        "uq_knowledge_documents_tenant_hash" not in uniques
        and "uq_knowledge_documents_tenant_hash" not in idx
    ):
        op.create_unique_constraint(
            "uq_knowledge_documents_tenant_hash",
            "knowledge_documents",
            ["tenant_id", "file_hash"],
        )

    cols = _col_names("knowledge_chunks")
    if "doc_id" not in cols:
        op.add_column(
            "knowledge_chunks",
            sa.Column("doc_id", sa.String(length=36), nullable=True),
        )
    if "page_no" not in cols:
        op.add_column(
            "knowledge_chunks",
            sa.Column("page_no", sa.Integer(), nullable=True),
        )
    fks = _fk_names("knowledge_chunks")
    if "fk_knowledge_chunks_doc_id" not in fks:
        op.create_foreign_key(
            "fk_knowledge_chunks_doc_id",
            "knowledge_chunks",
            "knowledge_documents",
            ["doc_id"],
            ["id"],
            ondelete="SET NULL",
        )
    chunk_idx = _index_names("knowledge_chunks")
    if "ix_knowledge_chunks_doc_id" not in chunk_idx:
        op.create_index(
            "ix_knowledge_chunks_doc_id",
            "knowledge_chunks",
            ["doc_id"],
        )


def downgrade() -> None:
    chunk_idx = _index_names("knowledge_chunks")
    if "ix_knowledge_chunks_doc_id" in chunk_idx:
        op.drop_index("ix_knowledge_chunks_doc_id", table_name="knowledge_chunks")
    fks = _fk_names("knowledge_chunks")
    if "fk_knowledge_chunks_doc_id" in fks:
        op.drop_constraint("fk_knowledge_chunks_doc_id", "knowledge_chunks", type_="foreignkey")
    cols = _col_names("knowledge_chunks")
    if "page_no" in cols:
        op.drop_column("knowledge_chunks", "page_no")
    if "doc_id" in cols:
        op.drop_column("knowledge_chunks", "doc_id")
    if "knowledge_documents" in _table_names():
        op.drop_table("knowledge_documents")
