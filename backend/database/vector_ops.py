"""向量操作封装 — 存储/检索/过期清理"""

from datetime import datetime, timedelta

from backend.database.pgvector_session import CacheEntry, ChatMessage, get_pg_session


def store_embedding(message_id: int, embedding: list[float]) -> None:
    """存储消息的 embedding"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        msg = session.query(ChatMessage).filter_by(id=message_id).first()
        if msg:
            msg.embedding = embedding
            session.commit()


def search_memories(
    tenant_id: str,
    query_vec: list[float],
    limit: int = 5,
    min_score: float = 0.7,
) -> list[dict]:
    """搜索相似记忆"""
    session_factory = get_pg_session()
    results = session_factory.search_similar(
        tenant_id=tenant_id,
        embedding=query_vec,
        limit=limit,
        min_score=min_score,
    )
    return [
        {
            "id": r.id,
            "content": r.content,
            "role": r.role,
            "emotion": r.emotion,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ]


def delete_expired_entries(ttl_hours: int = 24) -> int:
    """删除过期缓存条目"""
    session_factory = get_pg_session()
    cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
    with session_factory.Session() as session:
        deleted = (
            session.query(CacheEntry)
            .filter(CacheEntry.created_at < cutoff)
            .delete()
        )
        session.commit()
        return deleted
