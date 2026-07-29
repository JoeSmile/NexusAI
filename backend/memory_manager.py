#!/usr/bin/env python3
"""
记忆管理系统
负责记忆的向量化存储、检索和更新（pgvector）
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
from backend.vector_store import VectorStore
from backend.database import DatabaseManager
from backend.database import vector_ops
from backend.memory_extractor import MemoryExtractor
from config import Config


class MemoryManager:
    """记忆管理器 - 统一管理用户的长期记忆"""

    def __init__(self, tenant_id: str = "default"):
        """初始化记忆管理器"""
        self.tenant_id = tenant_id
        self.vector_store = VectorStore(tenant_id=tenant_id)
        self.extractor = MemoryExtractor()
        # 兼容旧字段：不再使用 Chroma collection
        self.memory_collection = True
    
    def process_conversation(self, session_id: str, user_id: str, 
                           user_message: str, bot_response: str,
                           emotion: Optional[str] = None, 
                           emotion_intensity: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        处理一次对话，提取并存储记忆
        
        Args:
            session_id: 会话ID
            user_id: 用户ID
            user_message: 用户消息
            bot_response: 机器人回复
            emotion: 情绪
            emotion_intensity: 情绪强度
            
        Returns:
            提取的记忆列表
        """
        # 1. 判断是否需要提取记忆
        if not self.extractor.should_extract_memory(user_message, emotion, emotion_intensity):
            return []
        
        # 2. 提取记忆
        memories = self.extractor.extract_memories(
            user_message, bot_response, emotion, emotion_intensity
        )
        
        # 3. 存储记忆
        stored_memories = []
        for memory in memories:
            stored_memory = self.store_memory(
                user_id=user_id,
                session_id=session_id,
                memory=memory
            )
            if stored_memory:
                stored_memories.append(stored_memory)
        
        return stored_memories
    
    def store_memory(self, user_id: str, session_id: str, 
                    memory: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        存储单条记忆到向量数据库
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            memory: 记忆数据
            
        Returns:
            存储的记忆（包含ID）
        """
        if not self.memory_collection:
            print("记忆集合未初始化")
            return None
        
        try:
            # 生成唯一 key
            import uuid
            memory_key = f"{memory.get('type', 'other')}_{uuid.uuid4().hex[:12]}"
            
            # 准备存储文本（用于向量化）
            memory_text = f"{memory.get('summary', '')} {memory.get('content', '')}".strip()
            
            mid = vector_ops.store_user_memory(
                tenant_id=self.tenant_id,
                user_id=user_id,
                key=memory_key,
                value=memory_text or json.dumps(memory, ensure_ascii=False),
                confidence=float(memory.get("importance", 0.5)),
                source=memory.get("extraction_method", "extracted"),
            )
            if mid is None:
                return None

            memory["id"] = str(mid)
            memory["user_id"] = user_id
            memory["session_id"] = session_id
            
            return memory
            
        except Exception as e:
            print(f"存储记忆失败: {e}")
            return None
    
    def retrieve_memories(self, user_id: str, query: str, 
                         n_results: int = 3,
                         days_limit: int = 7,
                         min_importance: float = 0.3,
                         emotion_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        检索相关记忆
        
        Args:
            user_id: 用户ID
            query: 查询文本（当前对话内容）
            n_results: 返回结果数量
            days_limit: 时间限制（天数），None表示不限制
            min_importance: 最小重要性阈值
            emotion_filter: 情绪过滤（可选）
            
        Returns:
            相关记忆列表
        """
        if not self.memory_collection:
            return []
        
        try:
            results = vector_ops.search_user_memories(
                tenant_id=self.tenant_id,
                user_id=user_id,
                query=query,
                limit=n_results * 2,
                min_score=0.3,
            )

            memories = []
            for item in results:
                importance = float(item.get("importance", 0))
                if importance < min_importance:
                    continue
                if emotion_filter and item.get("emotion") != emotion_filter:
                    continue
                if days_limit:
                    timestamp_str = item.get("timestamp", "")
                    if timestamp_str:
                        try:
                            memory_time = datetime.fromisoformat(timestamp_str)
                            if datetime.now() - memory_time > timedelta(days=days_limit):
                                continue
                        except Exception:
                            pass
                memories.append(item)
                if len(memories) >= n_results:
                    break

            memories.sort(
                key=lambda x: (x.get("importance", 0) * 0.5 + x.get("similarity", 0) * 0.5),
                reverse=True,
            )
            return memories[:n_results]
            
        except Exception as e:
            print(f"检索记忆失败: {e}")
            return []
    
    def get_user_emotion_trend(self, user_id: str, days: int = 7) -> Dict[str, Any]:
        """
        获取用户的情绪变化趋势
        
        Args:
            user_id: 用户ID
            days: 统计天数
            
        Returns:
            情绪趋势数据
        """
        if not self.memory_collection:
            return {"emotions": [], "trend": "稳定"}
        
        try:
            from backend.database.pgvector_session import UserMemory, get_pg_session

            cutoff_time = datetime.now() - timedelta(days=days)
            sf = get_pg_session()
            with sf.Session() as session:
                rows = (
                    session.query(UserMemory)
                    .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                    .limit(100)
                    .all()
                )

            emotion_counts = {}
            emotion_intensities = {}
            recent_emotions = []

            for row in rows:
                if row.created_at and row.created_at < cutoff_time:
                    continue
                emotion = "neutral"
                intensity = 5.0
                emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
                emotion_intensities.setdefault(emotion, []).append(intensity)
                recent_emotions.append(
                    {
                        "emotion": emotion,
                        "intensity": intensity,
                        "timestamp": row.created_at.isoformat() if row.created_at else "",
                    }
                )

            trend = "稳定"
            avg_intensities = {
                e: sum(v) / len(v) for e, v in emotion_intensities.items()
            }
            return {
                "emotions": [
                    {
                        "emotion": emotion,
                        "count": count,
                        "avg_intensity": avg_intensities.get(emotion, 5.0),
                    }
                    for emotion, count in sorted(
                        emotion_counts.items(), key=lambda x: x[1], reverse=True
                    )
                ],
                "trend": trend,
                "total_count": len(recent_emotions),
                "days": days,
            }
            
        except Exception as e:
            print(f"获取情绪趋势失败: {e}")
            return {"emotions": [], "trend": "未知", "error": str(e)}
    
    def get_important_memories(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        获取用户最重要的记忆
        
        Args:
            user_id: 用户ID
            limit: 返回数量
            
        Returns:
            重要记忆列表
        """
        if not self.memory_collection:
            return []
        
        try:
            from backend.database.pgvector_session import UserMemory, get_pg_session

            sf = get_pg_session()
            with sf.Session() as session:
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
                    "type": r.source or "other",
                    "emotion": "neutral",
                    "intensity": 5.0,
                    "importance": float(r.confidence or 0.5),
                    "timestamp": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
            
        except Exception as e:
            print(f"获取重要记忆失败: {e}")
            return []
    
    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """
        删除指定记忆
        
        Args:
            user_id: 用户ID
            memory_id: 记忆ID
            
        Returns:
            是否删除成功
        """
        if not self.memory_collection:
            return False
        
        try:
            from backend.database.pgvector_session import UserMemory, get_pg_session

            sf = get_pg_session()
            with sf.Session() as session:
                row = session.query(UserMemory).filter_by(id=int(memory_id)).first()
                if not row or row.user_id != user_id or row.tenant_id != self.tenant_id:
                    return False
                session.delete(row)
                session.commit()
            return True
        except Exception as e:
            print(f"删除记忆失败: {e}")
            return False
    
    def update_memory_importance(self, memory_id: str, new_importance: float) -> bool:
        """
        更新记忆的重要性
        
        Args:
            memory_id: 记忆ID
            new_importance: 新的重要性值(0-1)
            
        Returns:
            是否更新成功
        """
        if not self.memory_collection:
            return False

        if not 0.0 <= new_importance <= 1.0:
            raise ValueError("new_importance must be between 0 and 1")
        
        try:
            from backend.database.pgvector_session import UserMemory, get_pg_session

            sf = get_pg_session()
            with sf.Session() as session:
                row = session.query(UserMemory).filter_by(id=int(memory_id)).first()
                if not row:
                    return False
                row.confidence = float(new_importance)
                session.commit()
            return True
        except Exception as e:
            print(f"更新记忆重要性失败: {e}")
            return False

