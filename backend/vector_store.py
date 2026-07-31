"""
# DEPRECATED (Batch 3.1): 旧 VectorStore 门面。
# 新代码请用 pipeline memory 节点 / backend.database.vector_ops。
# 暂保留：MemoryManager / ChatEngine 仍依赖此 API。

向量存储 — pgvector 实现（替代原 ChromaDB VectorStore）

保持原有方法签名，供 MemoryManager / ChatEngine 兼容调用。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.database import vector_ops

logger = logging.getLogger(__name__)


class VectorStore:
    """pgvector 门面，兼容旧 Chroma VectorStore API。"""

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        # 兼容旧代码访问 .client / collections — 置空，调用方应走方法 API
        self.client = None
        self.conversation_collection = None
        self.knowledge_collection = None
        self.emotion_collection = None
        self.embedder = None
        logger.info("VectorStore 使用 pgvector 后端 (tenant=%s)", tenant_id)

    def add_conversation(
        self,
        session_id: str,
        message: str,
        response: str,
        emotion: str = None,
        user_id: str = "anonymous",
    ):
        vector_ops.add_chat_turn(
            tenant_id=self.tenant_id,
            session_id=session_id,
            user_id=user_id,
            user_message=message,
            assistant_message=response,
            emotion=emotion,
        )

    def search_similar_conversations(
        self, query: str, session_id: str = None, n_results: int = 5
    ):
        return vector_ops.search_similar_conversations(
            query=query,
            tenant_id=self.tenant_id,
            session_id=session_id,
            n_results=n_results,
        )

    def add_knowledge(self, text: str, category: str = "general", metadata: Dict = None):
        return vector_ops.add_knowledge(
            text=text,
            category=category,
            tenant_id=self.tenant_id,
            metadata=metadata,
        )

    def search_knowledge(self, query: str, n_results: int = 5, category: str = None):
        return vector_ops.search_knowledge(
            query=query,
            tenant_id=self.tenant_id,
            n_results=n_results,
        )

    def add_emotion_example(self, text: str, emotion: str, intensity: float = 5.0):
        # 情绪样本并入 knowledge，带 category
        return vector_ops.add_knowledge(
            text=text,
            category="emotion_example",
            tenant_id=self.tenant_id,
            metadata={"emotion": emotion, "intensity": intensity},
        )

    def search_emotion_patterns(self, query: str, n_results: int = 5):
        return vector_ops.search_knowledge(
            query=query,
            tenant_id=self.tenant_id,
            n_results=n_results,
        )

    def get_session_history(self, session_id: str, limit: int = 50) -> list[Dict[str, Any]]:
        from backend.database.pgvector_session import ChatMessage, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            rows = (
                session.query(ChatMessage)
                .filter_by(tenant_id=self.tenant_id, session_id=session_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "role": r.role,
                    "content": r.content,
                    "emotion": r.emotion,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
