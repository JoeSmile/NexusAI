"""embedding 维度 768 -> 1024 (text-embedding-v4)

Revision ID: 040_embed_dim_1024
Revises: 039_user_agreement
"""
from alembic import op

revision = "040_embed_dim_1024"
down_revision = "039_user_agreement"
branch_labels = None
depends_on = None

TABLES = [
    "chat_messages",
    "user_memories",
    "cold_memories",
    "skill_assets",
    "knowledge_chunks",
    "org_units",
]


def upgrade() -> None:
    # pgvector 不能把 vector(768) 直接 cast 成 1024；照抄 005：有列则先清向量再 ALTER。
    for t in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{t}' AND column_name='embedding') THEN "
            f"DELETE FROM {t} WHERE embedding IS NOT NULL; "
            f"ALTER TABLE {t} ALTER COLUMN embedding TYPE vector(1024); END IF; END $$;"
        )


def downgrade() -> None:
    for t in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{t}' AND column_name='embedding') THEN "
            f"DELETE FROM {t} WHERE embedding IS NOT NULL; "
            f"ALTER TABLE {t} ALTER COLUMN embedding TYPE vector(768); END IF; END $$;"
        )
