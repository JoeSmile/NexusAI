"""向量操作封装 — pgvector 存储/检索（替代 Chroma）"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text

from backend.database.embeddings import embed_text
from backend.database.pgvector_session import (
    CacheEntry,
    ChatMessage,
    KnowledgeChunk,
    UserMemory,
    get_pg_session,
)


def store_embedding(message_id: int, embedding: list[float]) -> None:
    """存储消息的 embedding"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        msg = session.query(ChatMessage).filter_by(id=message_id).first()
        if msg:
            msg.embedding = embedding
            session.commit()


def add_chat_turn(
    tenant_id: str,
    session_id: str,
    user_id: str,
    user_message: str,
    assistant_message: str,
    emotion: str | None = None,
) -> None:
    """写入一轮对话并生成 embedding（替代 VectorStore.add_conversation）"""
    session_factory = get_pg_session()
    combined = f"用户: {user_message}\n助手: {assistant_message}"
    if emotion:
        combined += f"\n情感: {emotion}"
    emb = embed_text(combined)
    with session_factory.Session() as session:
        session.add(
            ChatMessage(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                role="user",
                content=user_message,
                emotion=emotion,
                embedding=embed_text(user_message),
            )
        )
        session.add(
            ChatMessage(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=assistant_message,
                emotion=emotion,
                embedding=emb,
            )
        )
        session.commit()


def search_memories(
    tenant_id: str,
    query_vec: list[float],
    limit: int = 5,
    min_score: float = 0.7,
) -> list[dict]:
    """按向量搜索相似 chat_messages"""
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
            "session_id": r.session_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ]


def search_similar_conversations(
    query: str,
    tenant_id: str = "default",
    session_id: str | None = None,
    n_results: int = 5,
    min_score: float = 0.3,
) -> dict:
    """Chroma-compatible 返回结构: documents/metadatas/ids/distances"""
    vec = embed_text(query)
    session_factory = get_pg_session()
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
    with session_factory.Session() as session:
        sql = text(
            """
            SELECT id, session_id, content, emotion, created_at,
                   1 - (embedding <=> :vec::vector) AS similarity
            FROM chat_messages
            WHERE tenant_id = :tid
              AND embedding IS NOT NULL
              AND (:sid IS NULL OR session_id = :sid)
              AND 1 - (embedding <=> :vec::vector) >= :min_score
            ORDER BY embedding <=> :vec::vector
            LIMIT :lim
            """
        )
        rows = session.execute(
            sql,
            {
                "vec": vec_str,
                "tid": tenant_id,
                "sid": session_id,
                "min_score": min_score,
                "lim": n_results,
            },
        ).fetchall()

    docs, metas, ids, dists = [], [], [], []
    for r in rows:
        docs.append(r.content)
        metas.append(
            {
                "session_id": r.session_id,
                "emotion": r.emotion or "neutral",
                "timestamp": r.created_at.isoformat() if r.created_at else "",
            }
        )
        ids.append(str(r.id))
        # chroma distance ≈ 1 - similarity for cosine-ish
        dists.append(max(0.0, 1.0 - float(r.similarity or 0.0)))

    return {
        "documents": [docs],
        "metadatas": [metas],
        "ids": [ids],
        "distances": [dists],
    }


def store_user_memory(
    tenant_id: str,
    user_id: str,
    key: str,
    value: str,
    confidence: float = 1.0,
    source: str = "extracted",
) -> Optional[int]:
    """写入 UserMemory 并附 embedding"""
    emb = embed_text(f"{key} {value}")
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        existing = (
            session.query(UserMemory)
            .filter_by(tenant_id=tenant_id, user_id=user_id, key=key)
            .first()
        )
        if existing:
            existing.value = value
            existing.confidence = confidence
            existing.source = source
            existing.embedding = emb
            existing.updated_at = datetime.utcnow()
            session.commit()
            return existing.id
        row = UserMemory(
            tenant_id=tenant_id,
            user_id=user_id,
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            embedding=emb,
        )
        session.add(row)
        session.commit()
        return row.id


def search_user_memories(
    tenant_id: str,
    user_id: str,
    query: str,
    limit: int = 5,
    min_score: float = 0.3,
) -> list[dict[str, Any]]:
    """检索用户长期记忆"""
    vec = embed_text(query)
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text(
            """
            SELECT id, key, value, confidence, source, created_at,
                   1 - (embedding <=> :vec::vector) AS similarity
            FROM user_memories
            WHERE tenant_id = :tid
              AND user_id = :uid
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> :vec::vector) >= :min_score
            ORDER BY embedding <=> :vec::vector
            LIMIT :lim
            """
        )
        rows = session.execute(
            sql,
            {
                "vec": vec_str,
                "tid": tenant_id,
                "uid": user_id,
                "min_score": min_score,
                "lim": limit,
            },
        ).fetchall()
    return [
        {
            "id": str(r.id),
            "content": f"{r.key}: {r.value}",
            "key": r.key,
            "value": r.value,
            "importance": float(r.confidence or 0.5),
            "similarity": float(r.similarity or 0.0),
            "timestamp": r.created_at.isoformat() if r.created_at else "",
            "type": r.source or "other",
            "emotion": "neutral",
            "intensity": 5.0,
            "extraction_method": r.source or "unknown",
        }
        for r in rows
    ]


def add_knowledge(
    text: str,
    category: str = "general",
    tenant_id: str = "default",
    metadata: dict | None = None,
) -> int:
    emb = embed_text(text)
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = KnowledgeChunk(
            tenant_id=tenant_id,
            category=category,
            content=text,
            meta=metadata or {},
            embedding=emb,
        )
        session.add(row)
        session.commit()
        return row.id


def search_knowledge(
    query: str,
    tenant_id: str = "default",
    n_results: int = 5,
    min_score: float = 0.3,
) -> dict:
    vec = embed_text(query)
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text(
            """
            SELECT id, category, content, meta,
                   1 - (embedding <=> :vec::vector) AS similarity
            FROM knowledge_chunks
            WHERE tenant_id = :tid
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> :vec::vector) >= :min_score
            ORDER BY embedding <=> :vec::vector
            LIMIT :lim
            """
        )
        rows = session.execute(
            sql,
            {
                "vec": vec_str,
                "tid": tenant_id,
                "min_score": min_score,
                "lim": n_results,
            },
        ).fetchall()
    docs = [r.content for r in rows]
    metas = [{"category": r.category, **(r.meta or {})} for r in rows]
    ids = [str(r.id) for r in rows]
    dists = [max(0.0, 1.0 - float(r.similarity or 0.0)) for r in rows]
    return {
        "documents": [docs],
        "metadatas": [metas],
        "ids": [ids],
        "distances": [dists],
    }


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
