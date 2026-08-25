"""embedding 维度 1536 -> 768 (nomic-embed-text)

Revision ID: 005_embed_dim_768
Revises: 004_key_failover (或当前 head——运行时以实际为准，见 down_revision 注释)
"""
from alembic import op

revision = "005_embed_dim_768"
down_revision = "033_mcp_servers"

TABLES = [
    "chat_messages",
    "user_memories",
    "cold_memories",
    "skill_assets",
    "knowledge_chunks",
    "org_units",
]


def upgrade() -> None:
    # 数据量≈0：先清空旧 1536 向量，避免 ALTER TYPE 转换失败
    for t in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{t}' AND column_name='embedding') THEN "
            f"DELETE FROM {t} WHERE embedding IS NOT NULL; "
            f"ALTER TABLE {t} ALTER COLUMN embedding TYPE vector(768); END IF; END $$;"
        )
    # 本地演示库：旧数据语义无用（hash/补零），重嵌即可


def downgrade() -> None:
    for t in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{t}' AND column_name='embedding') THEN "
            f"DELETE FROM {t} WHERE embedding IS NOT NULL; "
            f"ALTER TABLE {t} ALTER COLUMN embedding TYPE vector(1536); END IF; END $$;"
        )
