#!/usr/bin/env python3
"""
增强版聊天服务
集成所有增强功能：
1. 增强版记忆管理（短期+长期+衰减）
2. 用户画像动态构建
3. 智能上下文组装
4. 主动回忆系统
"""

import uuid
from datetime import datetime
from functools import cached_property
from typing import Any

from backend.database import ChatMessage, ChatSession, DatabaseManager
from backend.models import ChatRequest, ChatResponse
from backend.services.enhanced_context_assembler import EnhancedContextAssembler
from backend.services.enhanced_memory_manager import EnhancedMemoryManager
from backend.services.user_profile_builder import UserProfileBuilder


class EnhancedChatService:
    """增强版聊天服务 — 组件按需惰性初始化（Task 19.07）"""

    def __init__(
        self,
        use_rag: bool = True,
        use_intent: bool = True,
        use_enhanced_processor: bool = True,
    ):
        self._cfg = {
            "use_rag": use_rag,
            "use_intent": use_intent,
            "use_enhanced_processor": use_enhanced_processor,
        }

    @cached_property
    def chat_engine(self):
        from backend.modules.llm.core.llm_core import ChatEngine

        return ChatEngine()

    @cached_property
    def memory_manager(self):
        return EnhancedMemoryManager()

    @cached_property
    def profile_builder(self):
        return UserProfileBuilder()

    @cached_property
    def context_assembler(self):
        return EnhancedContextAssembler()

    @cached_property
    def enhanced_processor(self):
        if not self._cfg.get("use_enhanced_processor"):
            return None
        try:
            from backend.modules.intent.core.enhanced_input_processor import (
                EnhancedInputProcessor,
            )

            return EnhancedInputProcessor(
                enable_jieba=True, enable_duplicate_check=True
            )
        except Exception:
            return None

    @property
    def enhanced_processor_enabled(self) -> bool:
        return self.enhanced_processor is not None

    @cached_property
    def rag_service(self):
        if not self._cfg.get("use_rag"):
            return None
        try:
            from backend.modules.rag.services.rag_service import RAGIntegrationService

            svc = RAGIntegrationService()
            if svc.rag_service.is_knowledge_available():
                return svc
        except Exception:
            return None
        return None

    @property
    def rag_enabled(self) -> bool:
        return self.rag_service is not None

    @cached_property
    def intent_service(self):
        if not self._cfg.get("use_intent"):
            return None
        try:
            from backend.modules.intent.services import IntentService

            return IntentService()
        except Exception:
            return None

    @property
    def intent_enabled(self) -> bool:
        return self.intent_service is not None

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        处理聊天请求（增强版流程）
        
        Args:
            request: 聊天请求
            
        Returns:
            聊天响应
        """
        # 生成会话ID（如果没有）
        if not request.session_id:
            request.session_id = str(uuid.uuid4())
        
        user_id = request.user_id or "anonymous"
        session_id = request.session_id
        message = request.message
        
        # ============ 第1步：输入预处理 ============
        preprocessed, message = await self._preprocess_input(user_id, message)
        if preprocessed and preprocessed.get("blocked"):
            return self._create_blocked_response(session_id, preprocessed)
        
        # ============ 第3步：意图识别 ============
        intent_result = await self._analyze_intent(user_id, message)
        
        # ============ 第5步：获取对话历史 ============
        chat_history = await self._get_conversation_history(session_id, limit=15)
        
        # ============ 第6步：组装增强上下文 ============
        context = await self.context_assembler.assemble_context(
            user_id=user_id,
            session_id=session_id,
            current_message=message,
            chat_history=chat_history
        )
        
        # ============ 第7步：构建增强Prompt ============
        system_prompt = self._build_system_prompt(context)
        self.context_assembler.build_prompt_context(
            context, system_prompt
        )
        
        # ============ 第8步：尝试RAG增强 ============
        rag_result = None
        if self.rag_enabled and self.rag_service:
            rag_result = await self._try_rag_enhancement(
                message, chat_history
            )
        
        # ============ 第9步：生成回复 ============
        response = await self._generate_response(
            request, rag_result, session_id
        )
        
        # ============ 第10步：添加上下文信息 ============
        self._enrich_response_context(
            response, context, intent_result, preprocessed, rag_result
        )
        
        # ============ 第11步：保存对话到数据库 ============
        await self._save_conversation(
            session_id, user_id, message, response.response
        )
        
        # ============ 第12步：处理并存储记忆 ============
        await self.memory_manager.process_conversation(
            session_id=session_id,
            user_id=user_id,
            user_message=message,
            bot_response=response.response
        )
        
        return response
    
    async def _preprocess_input(self, user_id: str, message: str) -> tuple:
        """输入预处理"""
        preprocessed = None
        if self.enhanced_processor_enabled and self.enhanced_processor:
            try:
                preprocessed = self.enhanced_processor.preprocess(message, user_id)
                if preprocessed["blocked"]:
                    return preprocessed, message
                message = preprocessed["cleaned"]
            except Exception as e:
                print(f"输入预处理失败: {e}")
        
        return preprocessed, message
    
    async def _analyze_intent(self, user_id: str, message: str) -> dict | None:
        """意图识别"""
        intent_result = None
        if self.intent_enabled and self.intent_service:
            try:
                intent_analysis = self.intent_service.analyze(message, user_id)
                intent_result = intent_analysis.get('intent', {})
                
                if intent_analysis.get('action_required', False):
                    print(f"⚠️ 检测到用户 {user_id} 的危机情况")
            except Exception as e:
                print(f"意图识别失败: {e}")
        
        return intent_result
    
    async def _get_conversation_history(self, session_id: str, limit: int = 15) -> list[dict]:
        """获取对话历史"""
        try:
            with DatabaseManager() as db:
                messages = db.get_session_messages(session_id, limit)
                return [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None
                    }
                    for msg in messages
                ]
        except Exception as e:
            print(f"获取对话历史失败: {e}")
            return []
    
    def _build_system_prompt(self, context: dict[str, Any]) -> str:
        """构建系统Prompt"""
        return """你是"ContextGate"，企业级 LLM 信息平台的智能助手，专业、准确、安全。"""
    
    async def _try_rag_enhancement(self, message: str,
                                  chat_history: list[dict]) -> dict | None:
        """尝试RAG增强"""
        try:
            rag_result = self.rag_service.enhance_response(
                message=message,
                conversation_history=chat_history
            )
            return rag_result
        except Exception as e:
            print(f"RAG增强失败: {e}")
            return None
    
    async def _generate_response(self, request: ChatRequest, rag_result: dict | None,
                                session_id: str) -> ChatResponse:
        """生成回复"""
        if rag_result and rag_result.get("use_rag"):
            # 使用RAG增强的回复
            return ChatResponse(
                response=rag_result["answer"],
                session_id=session_id,
                timestamp=datetime.now()
            )
        else:
            # 使用常规引擎
            try:
                return self.chat_engine.chat(request)
            except Exception as e:
                print(f"常规引擎调用失败: {e}")
                return ChatResponse(
                    response="抱歉，我遇到了一些技术问题，请稍后再试。",
                    session_id=session_id,
                    timestamp=datetime.now()
                )
    
    def _enrich_response_context(self, response: ChatResponse, context: dict[str, Any],
                                 intent_result: dict | None, preprocessed: dict | None,
                                 rag_result: dict | None):
        """丰富响应上下文信息"""
        response.context = {
            # 记忆信息
            "short_term_messages": context.get("short_term_memory", {}).get("count", 0),
            "long_term_memories": context.get("long_term_memory", {}).get("count", 0),
            "important_turns": len(context.get("short_term_memory", {}).get("important_turns", [])),
            
            # 用户画像
            "user_profile_summary": context.get("user_profile", {}).get("summary", ""),
            
            # 对话图谱
            "conversation_nodes": len(context.get("conversation_graph", {}).get("nodes", {})),
            "conversation_edges": len(context.get("conversation_graph", {}).get("edges", [])),
            
            # 意图识别
            "intent": intent_result.get('intent') if intent_result else None,
            "intent_confidence": intent_result.get('confidence') if intent_result else None,
            
            # 输入处理
            "input_preprocessed": preprocessed is not None,
            "input_metadata": preprocessed.get("metadata") if preprocessed else None,
            
            # RAG使用情况
            "used_rag": bool(rag_result and rag_result.get("use_rag")),
            "knowledge_sources": len(rag_result.get("sources", [])) if rag_result else 0,
            
            # 系统版本
            "system_version": "enhanced_v1.0"
        }
    
    async def _save_conversation(self, session_id: str, user_id: str,
                                user_message: str, bot_response: str):
        """保存对话到数据库"""
        try:
            with DatabaseManager() as db:
                # 检查会话是否存在
                existing_session = db.db.query(ChatSession).filter(
                    ChatSession.session_id == session_id
                ).first()
                
                if not existing_session:
                    db.create_session(session_id, user_id)
                
                # 保存用户消息
                db.save_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="user",
                    content=user_message,
                )
                
                # 保存助手消息
                db.save_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content=bot_response,
                )
                
        except Exception as e:
            print(f"保存对话失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _create_blocked_response(self, session_id: str, preprocessed: dict) -> ChatResponse:
        """创建被阻止的响应"""
        return ChatResponse(
            response=preprocessed.get("friendly_message", "输入无效，请重新输入"),
            session_id=session_id,
            timestamp=datetime.now(),
            context={
                "blocked": True,
                "reason": preprocessed["warnings"],
                "input_validation": "failed"
            }
        )
    
    # ============ 辅助接口方法 ============
    
    async def get_session_history(self, session_id: str, limit: int = 20) -> dict[str, Any]:
        """获取会话历史"""
        try:
            with DatabaseManager() as db:
                messages = db.get_session_messages(session_id, limit)
                
                if not messages:
                    return {
                        "session_id": session_id,
                        "messages": [],
                        "total": 0
                    }
                
                return {
                    "session_id": session_id,
                    "messages": [
                        {
                            "id": msg.id,
                            "role": msg.role,
                            "content": msg.content,
                            "timestamp": msg.created_at.isoformat() if msg.created_at else None
                        }
                        for msg in messages
                    ],
                    "total": len(messages)
                }
        except Exception as e:
            print(f"获取会话历史失败: {e}")
            return {
                "session_id": session_id,
                "messages": [],
                "total": 0,
                "error": str(e)
            }
    
    async def get_user_sessions(self, user_id: str, limit: int = 50) -> dict[str, Any]:
        """获取用户的所有会话"""
        try:
            with DatabaseManager() as db:
                sessions = db.get_user_sessions(user_id, limit)
                
                session_list = []
                for session in sessions:
                    # 检查会话是否有消息
                    message_count = db.db.query(ChatMessage)\
                        .filter(ChatMessage.session_id == session.session_id)\
                        .count()
                    
                    # 如果会话没有消息，跳过（不显示在历史列表中）
                    if message_count == 0:
                        continue
                    
                    # 获取会话的第一条消息作为标题
                    first_message = db.db.query(ChatMessage)\
                        .filter(ChatMessage.session_id == session.session_id)\
                        .filter(ChatMessage.role == 'user')\
                        .order_by(ChatMessage.created_at.asc())\
                        .first()
                    
                    # 获取会话的最后一条消息作为预览
                    last_message = db.db.query(ChatMessage)\
                        .filter(ChatMessage.session_id == session.session_id)\
                        .order_by(ChatMessage.created_at.desc())\
                        .first()
                    
                    title = first_message.content[:30] + "..." if first_message and len(first_message.content) > 30 else (first_message.content if first_message else "新对话")
                    
                    # 生成预览文本（最后一条消息的内容，最多50个字符）
                    preview = ""
                    if last_message:
                        preview = last_message.content[:50] + "..." if len(last_message.content) > 50 else last_message.content
                    
                    session_list.append({
                        "session_id": session.session_id,
                        "title": title,
                        "preview": preview,
                        "message_count": message_count,
                        "created_at": session.created_at.isoformat() if session.created_at else None,
                        "updated_at": session.updated_at.isoformat() if session.updated_at else None
                    })
                
                return {
                    "user_id": user_id,
                    "sessions": session_list,
                    "total": len(session_list)
                }
        except Exception as e:
            print(f"获取用户会话列表失败: {e}")
            return {
                "user_id": user_id,
                "sessions": [],
                "total": 0,
                "error": str(e)
            }
    
    async def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        try:
            with DatabaseManager() as db:
                return db.delete_session(session_id)
        except Exception as e:
            print(f"删除会话失败: {e}")
            return False
    
    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """获取用户画像"""
        return await self.profile_builder.build_profile(user_id)
    
    async def get_user_memories(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取用户重要记忆"""
        return await self.memory_manager.get_important_memories(user_id, limit)
    
