"""
Memory Hub - 记忆中枢

统一的记忆管理接口，整合：
- 短期记忆（工作记忆）
- 长期记忆（情景记忆、语义记忆）
- 用户画像
- 行为日志
"""

from datetime import datetime, timedelta
from typing import Any

from backend.database import User, get_db

try:
    from backend.memory_manager import MemoryManager
except ImportError:  # Batch 3.1.3 removed
    MemoryManager = None  # type: ignore


class MemoryHub:
    """记忆中枢 - Agent的记忆系统核心"""
    
    def __init__(self, memory_manager=None):
        """
        初始化记忆中枢
        
        Args:
            memory_manager: 现有的记忆管理器（可选，用于复用）
        """
        if memory_manager is not None:
            self.memory_manager = memory_manager
        elif MemoryManager is not None:
            self.memory_manager = MemoryManager()
        else:
            self.memory_manager = None
        
        # 短期记忆（内存缓存）
        self.working_memory = {
            "conversation": [],      # 当前对话上下文
            "active_tasks": [],      # 激活的任务
            "temp_variables": {}     # 临时变量
        }
        
        # 记忆类型定义
        self.memory_types = {
            "episodic": "情景记忆",      # 事件、经历
            "semantic": "语义记忆",      # 知识、概念
            "procedural": "程序记忆",    # 技能、策略
            "conversation": "对话记忆"   # 对话历史
        }
    
    def encode(self, experience: dict[str, Any]) -> dict[str, Any]:
        """
        编码：将新经验转换为记忆
        
        Args:
            experience: 经验数据，包含content, context等
            
        Returns:
            编码后的记忆对象
        """
        memory = {
            "content": experience.get("content", ""),
            "context": self.working_memory["conversation"][-5:],  # 最近5轮对话
            "timestamp": datetime.now(),
            "importance": self._calculate_importance(experience),
            "memory_type": self._infer_memory_type(experience),
            "user_id": experience.get("user_id"),
            "metadata": experience.get("metadata", {})
        }
        
        return memory
    
    def consolidate(self, memory: dict[str, Any]) -> bool:
        """
        巩固：将工作记忆转移到长期记忆
        
        Args:
            memory: 待巩固的记忆
            
        Returns:
            是否成功巩固
        """
        try:
            if self.memory_manager is None:
                return False
            # 情景记忆：存储事件到向量数据库
            if memory["memory_type"] == "episodic":
                self.memory_manager.save_memory(
                    user_id=memory["user_id"],
                    content=memory["content"],
                    importance=memory["importance"],
                    metadata=memory.get("metadata", {})
                )
            
            # 对话记忆：存储到数据库
            elif memory["memory_type"] == "conversation":
                self._save_conversation_memory(memory)
            
            # 语义记忆：提取知识并存储
            elif memory["memory_type"] == "semantic" and memory["importance"] > 0.8:
                knowledge = self._extract_knowledge(memory)
                if knowledge:
                    self.memory_manager.save_memory(
                        user_id=memory["user_id"],
                        content=knowledge,
                        importance=memory["importance"],
                        metadata={"type": "knowledge", **memory.get("metadata", {})}
                    )
            
            return True
            
        except Exception as e:
            print(f"记忆巩固失败: {e!s}")
            return False
    
    def retrieve(
        self, 
        query: str, 
        user_id: str,
        context: dict[str, Any] | None = None,
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        检索：基于查询和上下文检索相关记忆
        
        Args:
            query: 搜索查询
            user_id: 用户ID
            context: 上下文信息（时间等）
            top_k: 返回Top-K记忆
            
        Returns:
            相关记忆列表
        """
        context = context or {}
        results = []
        
        # 1. 向量语义检索（相似度）
        try:
            if self.memory_manager is not None:
                semantic_results = self.memory_manager.search_memories(
                    user_id=user_id,
                    query=query,
                    top_k=top_k,
                    min_importance=0.3
                )
                results.extend(semantic_results)
        except Exception as e:
            print(f"语义检索失败: {e!s}")
        
        # 2. 时间序列检索（近期优先）
        if context.get("time_range"):
            try:
                temporal_results = self._search_recent(
                    user_id=user_id,
                    days=context.get("time_range", 7),
                    limit=3
                )
                results.extend(temporal_results)
            except Exception as e:
                print(f"时间检索失败: {e!s}")
        
        # 合并去重，按重要性和相似度排序
        unique_results = self._merge_and_rank(results, top_k)
        
        return unique_results
    
    def update_working_memory(
        self, 
        conversation: list[dict] | None = None,
        tasks: list[dict] | None = None,
        variables: dict | None = None
    ):
        """
        更新短期记忆（工作记忆）
        
        Args:
            conversation: 对话历史
            tasks: 任务列表
            variables: 临时变量
        """
        if conversation is not None:
            # 只保留最近10轮对话
            self.working_memory["conversation"] = conversation[-10:]
        
        if tasks is not None:
            self.working_memory["active_tasks"] = tasks
        
        if variables is not None:
            self.working_memory["temp_variables"].update(variables)
    
    def get_working_memory(self) -> dict[str, Any]:
        """获取当前工作记忆"""
        return self.working_memory.copy()
    
    def clear_working_memory(self):
        """清空工作记忆"""
        self.working_memory = {
            "conversation": [],
            "active_tasks": [],
            "temp_variables": {}
        }
    
    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """
        获取用户画像
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户画像数据
        """
        try:
            db = next(get_db())
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user:
                return {}
            
            profile = {
                "user_id": user.id,
                "username": user.username,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "total_conversations": self._get_conversation_count(user_id),
                "interests": self._extract_interests(user_id)
            }
            
            return profile
            
        except Exception as e:
            print(f"获取用户画像失败: {e!s}")
            return {}
    
    def get_action_log(
        self, 
        user_id: str, 
        days: int = 7,
        limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        获取用户行为日志
        
        Args:
            user_id: 用户ID
            days: 查询天数
            limit: 返回数量限制
            
        Returns:
            行为日志列表
        """
        try:
            db = next(get_db())
            since_date = datetime.now() - timedelta(days=days)
            
            messages = db.query(Message).join(Conversation).filter(
                Conversation.user_id == user_id,
                Message.created_at >= since_date
            ).order_by(Message.created_at.desc()).limit(limit).all()
            
            action_log = []
            for msg in messages:
                action_log.append({
                    "action": "message",
                    "content": msg.content[:100],  # 截断内容
                    "role": msg.role,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None
                })
            
            return action_log
            
        except Exception as e:
            print(f"获取行为日志失败: {e!s}")
            return []
    
    # ==================== 私有辅助方法 ====================
    
    def _calculate_importance(self, experience: dict[str, Any]) -> float:
        """
        计算记忆重要性
        
        规则：
        1. 包含特定关键词（考试、面试等）提高重要性
        2. 内容长度影响重要性
        """
        importance = 0.5  # 基础重要性
        
        # 关键词影响
        content = experience.get("content", "")
        important_keywords = ["考试", "面试", "生病", "家人", "工作", "健康"]
        if any(kw in content for kw in important_keywords):
            importance += 0.2
        
        # 内容长度影响
        if len(content) > 50:
            importance += 0.1
        
        return min(importance, 1.0)
    
    def _infer_memory_type(self, experience: dict[str, Any]) -> str:
        """推断记忆类型"""
        content = experience.get("content", "")
        
        # 事件关键词
        event_keywords = ["今天", "昨天", "刚刚", "发生", "遇到", "经历"]
        if any(kw in content for kw in event_keywords):
            return "episodic"
        
        # 对话记忆
        if experience.get("role") in ["user", "assistant"]:
            return "conversation"
        
        # 默认为语义记忆
        return "semantic"
    
    def _extract_knowledge(self, memory: dict[str, Any]) -> str | None:
        """从记忆中提取知识"""
        # 简化实现：如果包含"学到"、"发现"等关键词，提取知识
        content = memory.get("content", "")
        knowledge_keywords = ["学到", "发现", "了解到", "知道了", "明白了"]
        
        if any(kw in content for kw in knowledge_keywords):
            return content
        
        return None
    
    def _save_conversation_memory(self, memory: dict[str, Any]):
        """保存对话记忆到数据库"""
        try:
            db = next(get_db())
            
            # 查找或创建对话
            conversation = db.query(Conversation).filter(
                Conversation.user_id == memory["user_id"]
            ).order_by(Conversation.created_at.desc()).first()
            
            if conversation:
                # 保存消息
                message = Message(
                    conversation_id=conversation.id,
                    role=memory.get("role", "user"),
                    content=memory["content"]
                )
                db.add(message)
                db.commit()
        
        except Exception as e:
            print(f"保存对话记忆失败: {e!s}")
    
    def _search_recent(
        self, 
        user_id: str, 
        days: int = 7, 
        limit: int = 5
    ) -> list[dict[str, Any]]:
        """搜索近期记忆"""
        try:
            db = next(get_db())
            since_date = datetime.now() - timedelta(days=days)
            
            messages = db.query(Message).join(Conversation).filter(
                Conversation.user_id == user_id,
                Message.created_at >= since_date,
                Message.role == "user"
            ).order_by(Message.created_at.desc()).limit(limit).all()
            
            results = []
            for msg in messages:
                results.append({
                    "content": msg.content,
                    "timestamp": msg.created_at,
                    "importance": 0.7  # 近期记忆默认较重要
                })
            
            return results
            
        except Exception as e:
            print(f"近期记忆搜索失败: {e!s}")
            return []
    

    def _merge_and_rank(
        self, 
        results: list[dict[str, Any]], 
        top_k: int
    ) -> list[dict[str, Any]]:
        """合并去重并排序记忆"""
        # 简单去重（基于内容）
        seen_contents = set()
        unique_results = []
        
        for result in results:
            content = result.get("content", "")
            if content and content not in seen_contents:
                seen_contents.add(content)
                unique_results.append(result)
        
        # 按重要性和时间排序
        unique_results.sort(
            key=lambda x: (
                x.get("importance", 0.5),
                x.get("timestamp", datetime.min)
            ),
            reverse=True
        )
        
        return unique_results[:top_k]
    
    def _get_conversation_count(self, user_id: str) -> int:
        """获取用户对话总数"""
        try:
            db = next(get_db())
            count = db.query(Conversation).filter(
                Conversation.user_id == user_id
            ).count()
            return count
        except:
            return 0
    

    def _extract_interests(self, user_id: str) -> list[str]:
        """提取用户兴趣"""
        # 简化实现：基于关键词统计
        try:
            db = next(get_db())
            
            messages = db.query(Message).join(Conversation).filter(
                Conversation.user_id == user_id,
                Message.role == "user"
            ).limit(100).all()
            
            interest_keywords = {
                "阅读": ["书", "读", "小说", "阅读"],
                "音乐": ["音乐", "歌", "听歌", "演唱会"],
                "运动": ["运动", "跑步", "健身", "游泳"],
                "电影": ["电影", "影片", "看电影"],
                "旅游": ["旅游", "旅行", "出游", "景点"]
            }
            
            interest_counts = {interest: 0 for interest in interest_keywords}
            
            for msg in messages:
                content = msg.content
                for interest, keywords in interest_keywords.items():
                    if any(kw in content for kw in keywords):
                        interest_counts[interest] += 1
            
            # 返回提及次数>2的兴趣
            interests = [k for k, v in interest_counts.items() if v > 2]
            return interests
            
        except Exception as e:
            print(f"提取兴趣失败: {e!s}")
            return []
    


# 单例模式
_memory_hub_instance = None

def get_memory_hub() -> MemoryHub:
    """获取全局MemoryHub实例"""
    global _memory_hub_instance
    if _memory_hub_instance is None:
        _memory_hub_instance = MemoryHub()
    return _memory_hub_instance

