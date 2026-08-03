#!/usr/bin/env python3
"""记忆服务层 — pgvector UserMemory（替代旧 MemoryManager / MemoryExtractor）"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.database.pgvector_session import UserMemory, get_pg_session
from backend.database.vector_ops import search_user_memories, store_user_memory


class MemoryService:
    """记忆服务 — 统一走 pgvector"""

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id

    async def process_and_store_memories(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        bot_response: str,
    ) -> list[dict[str, Any]]:
        key = f"turn:{session_id}"
        value = f"user: {user_message}\nassistant: {bot_response}"
        mid = store_user_memory(
            tenant_id=self.tenant_id,
            user_id=user_id,
            key=key,
            value=value,
            confidence=0.5,
            source="conversation",
        )
        if mid is None:
            return []
        return [
            {
                "id": str(mid),
                "user_id": user_id,
                "session_id": session_id,
                "content": value,
                "type": "conversation",
                "importance": 0.5,
            }
        ]

    async def retrieve_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        results = search_user_memories(
            tenant_id=self.tenant_id,
            user_id=user_id,
            query=query,
            limit=limit,
        )
        if memory_type:
            results = [r for r in results if r.get("type") == memory_type]
        return results


    async def get_important_memories(
        self, user_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            rows = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .order_by(UserMemory.confidence.desc())
                .limit(limit)
                .all()
            )
        return [
            {
                "id": str(r.id),
                "content": f"{r.key}: {r.value}",
                "key": r.key,
                "value": r.value,
                "importance": float(r.confidence or 0.5),
                "type": r.source or "other",
            }
            for r in rows
        ]

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        from backend.core.memory_service import get_unified_memory_service

        return await get_unified_memory_service(self.tenant_id).delete_warm(
            user_id=user_id, memory_id=memory_id
        )

    async def forget_user(self, user_id: str) -> dict[str, Any]:
        """被遗忘权：删 warm+cold，脱敏 chat_messages。"""
        from backend.core.memory_service import get_unified_memory_service

        return await get_unified_memory_service(self.tenant_id).forget_user(user_id)

    async def update_memory_importance(
        self, user_id: str, memory_id: str, new_importance: float
    ) -> bool:
        if not 0.0 <= new_importance <= 1.0:
            raise ValueError("new_importance must be between 0 and 1")
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id, id=int(memory_id))
                .first()
            )
            if not row:
                return False
            row.confidence = new_importance
            session.commit()
            return True

    async def get_user_memories_list(
        self,
        user_id: str,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            q = session.query(UserMemory).filter_by(
                tenant_id=self.tenant_id, user_id=user_id
            )
            if memory_type:
                q = q.filter(UserMemory.source == memory_type)
            rows = q.order_by(UserMemory.updated_at.desc()).limit(limit).all()
        return [
            {
                "id": str(r.id),
                "content": f"{r.key}: {r.value}",
                "key": r.key,
                "value": r.value,
                "importance": float(r.confidence or 0.5),
                "type": r.source or "other",
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    async def get_memory_statistics(self, user_id: str) -> dict[str, Any]:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            total = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .count()
            )
            by_source = session.execute(
                text(
                    """
                    SELECT COALESCE(source, 'other') AS src, COUNT(*) AS n
                    FROM user_memories
                    WHERE tenant_id = :tid AND user_id = :uid
                    GROUP BY src
                    """
                ),
                {"tid": self.tenant_id, "uid": user_id},
            ).fetchall()
        return {
            "user_id": user_id,
            "total": total,
            "by_type": {r.src: r.n for r in by_source},
        }
