#!/usr/bin/env python3
"""
简化版LangChain聊天引擎（支持LCEL表达式，Python 3.10+）
"""
import uuid

import requests

# 导入 LangChain (Python 3.10+, langchain 0.2.x+)
try:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    ChatPromptTemplate = None
    StrOutputParser = None
    print("提示: LangChain 模块未安装，将使用传统 HTTP 请求方式")

# 数据库和模型
from backend.database import DatabaseManager, create_tables
from backend.models import ChatResponse
from backend.modules.llm.harness import resolve_llm_settings, try_create_chat_openai

# 导入ContextGatePrompt配置
from backend.system_prompt import (
    SYSTEM_PROMPT,
    build_full_prompt,
    validate_and_filter_input,
)

# 尝试导入向量数据库（可选）
try:
    from backend.vector_store import VectorStore
    VECTOR_STORE_AVAILABLE = True
except ImportError as e:
    VECTOR_STORE_AVAILABLE = False
    print(f"提示: 向量数据库模块未安装 ({e}), 将仅使用MySQL短期记忆")


class ChatEngine:
    def __init__(self):
        # 初始化API配置 - 经 LLM Harness 统一解析
        _cfg = resolve_llm_settings()
        self.api_key = _cfg.api_key
        self.api_base_url = _cfg.base_url
        self.model = _cfg.model
        
        if not self.api_key:
            print("警告: API_KEY 未设置，将使用本地fallback模式")
            self.api_key = None
        
        # 创建数据库表
        create_tables()
        
        # 初始化向量数据库（长期记忆）
        if VECTOR_STORE_AVAILABLE:
            try:
                self.vector_store = VectorStore()
                print("✓ 向量数据库 (pgvector) 初始化成功")
            except Exception as e:
                print(f"警告: 向量数据库初始化失败: {e}，将仅使用MySQL")
                self.vector_store = None
        else:
            self.vector_store = None
            print("⚠ 向量数据库未安装，仅使用MySQL短期记忆")
        
        # 初始化 LangChain 组件（LCEL 表达式）- 如果可用
        if self.api_key and LANGCHAIN_AVAILABLE:
            try:
                # 1. 经 LLM Harness 创建 OpenAI 兼容客户端（与 Hermes 式网关一致）
                self.llm = try_create_chat_openai(temperature=0.7, model=self.model)
                if not self.llm:
                    print("警告: LangChain ChatOpenAI 不可用，将使用传统方式")
                    self.chain = None
                else:
                    # 2. 定义 AI 人格与行为准则（使用完整的ContextGatePrompt）
                    self.template = f"""{SYSTEM_PROMPT}

{{long_term_memory}}

对话历史：
{{history}}

用户：{{input}}
ContextGate："""

                    # 3. 创建提示模板和链（LCEL表达式）
                    self.prompt = ChatPromptTemplate.from_template(self.template)
                    self.output_parser = StrOutputParser()
                    self.chain = self.prompt | self.llm | self.output_parser
                    print("✓ LangChain LCEL 链初始化成功")
            except Exception as e:
                print(f"警告: LangChain 初始化失败，将使用传统方式: {e}")
                self.llm = None
                self.chain = None
        else:
            self.llm = None
            self.chain = None
        
    def is_safe_input(self, text):
        """
        安全检查（使用完整的验证机制）
        Returns: (is_valid, filtered_response)
        """
        return validate_and_filter_input(text)
    
    def get_openai_response(self, user_input, user_id, session_id):
        """使用 LangChain LCEL 链生成回应（如果可用），否则使用传统HTTP请求"""
        # 安全检查
        is_safe, warning = self.is_safe_input(user_input)
        if not is_safe:
            return warning
        
        # 如果没有API key，直接使用fallback
        if not self.api_key:
            return self._get_fallback_response(user_input)
        
        # 构建历史对话（短期记忆 - MySQL）
        db_manager = DatabaseManager()
        with db_manager as db:
            recent_messages = db.get_session_messages(session_id, limit=10)
            history_text = ""
            for msg in reversed(recent_messages[-5:]):  # 最近5条消息
                history_text += "{}: {}\n".format('用户' if msg.role == 'user' else 'ContextGate', msg.content)
        
        # 从向量数据库检索相似对话（长期记忆）
        long_term_context = ""
        if self.vector_store:
            try:
                # 检索相似的历史对话（跨会话）
                similar_conversations = self.vector_store.search_similar_conversations(
                    query=user_input,
                    session_id=None,  # 不限制会话，检索所有历史
                    n_results=3
                )
                
                if similar_conversations and similar_conversations['documents']:
                    long_term_context = "\n相关历史对话参考：\n"
                    for doc in similar_conversations['documents'][0][:2]:  # 取前2个最相似的
                        long_term_context += f"- {doc[:100]}\n"  # 限制长度
                    long_term_context += "\n"
            except Exception as e:
                print(f"向量检索失败: {e}")
        
        # 优先使用 LCEL 链（如果可用）
        if self.chain:
            try:
                # 4. 使用链生成回应 (chain.invoke) - 包含长期记忆
                response = self.chain.invoke({
                    "long_term_memory": long_term_context,
                    "history": history_text.strip(),
                    "input": user_input
                })
                return response
            except Exception as e:
                print(f"LangChain调用失败 ({self.model}): {e}，尝试传统方式")
                # 继续使用传统方式
        
        # 使用传统 HTTP 请求方式（兼容模式）
        return self._call_api_traditional(user_input, history_text, long_term_context)
    
    def _call_api_traditional(self, user_input, history_text, long_term_context=""):
        """传统HTTP请求方式调用API（兼容旧环境）"""
        # 使用完整的ContextGatePrompt构建提示词
        full_prompt = build_full_prompt(
            user_input=user_input,
            history_text=history_text,
            long_term_memory=long_term_context
        )
        
        # 调用API (支持Qwen和OpenAI)
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": full_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 300  # 控制响应长度（3-4句话）
            }
            
            api_url = f"{self.api_base_url}/chat/completions"
            response = requests.post(
                api_url,
                headers=headers,
                json=data,
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            else:
                print(f"API错误 ({self.model}): {response.status_code} - {response.text}")
                return self._get_fallback_response(user_input)
                
        except Exception as e:
            print(f"API调用失败 ({self.model}): {e}")
            return self._get_fallback_response(user_input)
    
    def _get_fallback_response(self, user_input):
        """提供备选回应（API 不可用时）"""
        return (
            "我暂时无法连接模型服务。请检查 LLM API 配置后重试。"
            f"（收到您的消息：{user_input[:80]}…）"
        )

    def chat(self, request):
        """处理聊天请求"""
        session_id = request.session_id or str(uuid.uuid4())
        user_id = request.user_id or "anonymous"
        
        print(f"Chat请求: session_id={session_id}, user_id={user_id}, message={request.message[:50]}...")
        
        # 保存用户消息到数据库
        try:
            db_manager = DatabaseManager()
            with db_manager as db:
                # 如果是新会话，创建会话记录
                if not request.session_id:
                    print(f"创建新会话: {session_id} for user: {user_id}")
                    db.create_session(session_id, user_id)
                    print("会话创建完成")
                
                db.save_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="user",
                    content=request.message,
                )
        except Exception as e:
            print(f"数据库操作失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 生成回应
        response_text = self.get_openai_response(request.message, user_id, session_id)
        
        # 保存助手消息到数据库
        db_manager = DatabaseManager()
        with db_manager as db:
            db.save_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=response_text,
            )
        
        return ChatResponse(
            response=response_text,
            session_id=session_id,
        )

    def get_session_summary(self, session_id):
        """获取会话摘要"""
        db_manager = DatabaseManager()
        with db_manager as db:
            messages = db.get_session_messages(session_id)
            
            if not messages:
                return {"error": "会话不存在"}
            
            return {
                "session_id": session_id,
                "message_count": len(messages),
                "created_at": messages[-1].created_at.isoformat() if messages else None,
                "updated_at": messages[0].created_at.isoformat() if messages else None
            }


