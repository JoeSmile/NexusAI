"""加载记忆节点 — 从 pgvector 加载 L1(热) + L2(温) 记忆"""

from __future__ import annotations

from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session
from backend.pipeline.state import PipelineState


async def load_memory(state: PipelineState) -> PipelineState:
    """加载用户记忆"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]

    try:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            recent = session.execute(
                text("""
                    SELECT role, content, emotion, created_at
                    FROM chat_messages
                    WHERE tenant_id = :tid AND user_id = :uid
                    ORDER BY created_at DESC LIMIT 5
                """),
                {"tid": tenant_id, "uid": user_id},
            ).fetchall()

            profile = session.execute(
                text("""
                    SELECT key, value FROM user_memories
                    WHERE tenant_id = :tid AND user_id = :uid
                """),
                {"tid": tenant_id, "uid": user_id},
            ).fetchall()

        state["hot_memory"] = [
            {"role": r.role, "content": r.content, "emotion": r.emotion}
            for r in reversed(recent)
        ]
        state["warm_memory"] = {p.key: p.value for p in profile}
    except Exception:
        # 旧库缺 tenant_id 等列时不阻断管线
        state["hot_memory"] = []
        state["warm_memory"] = {}

    return state
