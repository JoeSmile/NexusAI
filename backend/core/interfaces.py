#!/usr/bin/env python3
"""
接口定义模块
定义系统的核心接口和抽象类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..models import ChatRequest, ChatResponse


@dataclass

@dataclass
class MemoryInfo:
    """记忆信息"""
    id: str
    content: str
    importance: float
    timestamp: str
    metadata: dict[str, Any]


@dataclass
class ContextInfo:
    """上下文信息"""
    user_id: str
    session_id: str
    memories: list[MemoryInfo]
    user_profile: dict[str, Any]
    conversation_summary: str


@dataclass
class RAGResult:
    """RAG检索结果"""
    answer: str
    sources: list[dict[str, Any]]
    confidence: float
    knowledge_count: int
    used_context: bool


class IChatEngine(ABC):
    """聊天引擎接口"""
    
    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """处理聊天请求"""
    
    @abstractmethod
    async def get_session_summary(self, session_id: str) -> dict[str, Any]:
        """获取会话摘要"""
    


class IMemoryService(ABC):
    """记忆服务接口"""
    
    @abstractmethod
    async def extract_memories(self, text: str) -> list[dict[str, Any]]:
        """从文本中提取记忆"""
    
    @abstractmethod
    async def store_memory(self, memory: dict[str, Any]) -> str:
        """存储记忆"""
    
    @abstractmethod
    async def retrieve_memories(
        self,
        user_id: str,
        query: str | None = None,
        limit: int = 10
    ) -> list[MemoryInfo]:
        """检索记忆"""
    
    @abstractmethod
    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        """更新记忆"""
    
    @abstractmethod
    async def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
    
    @abstractmethod
    async def get_memory_stats(self, user_id: str) -> dict[str, Any]:
        """获取记忆统计信息"""


class IContextService(ABC):
    """上下文服务接口"""
    
    @abstractmethod
    async def build_context(
        self,
        user_id: str,
        session_id: str,
        current_message: str,

    ) -> ContextInfo:
        """构建对话上下文"""
    
    @abstractmethod
    async def update_context(
        self,
        context: ContextInfo,
        new_message: str
    ) -> ContextInfo:
        """更新上下文"""
    
    @abstractmethod
    async def clear_context(self, user_id: str, session_id: str) -> bool:
        """清空上下文"""


class IRAGService(ABC):
    """RAG服务接口"""
    
    @abstractmethod
    async def ask(self, question: str, search_k: int = 3) -> RAGResult:
        """向知识库提问"""
    
    @abstractmethod
    async def ask_with_context(
        self,
        question: str,
        conversation_history: list[dict[str, str]] | None = None,
        search_k: int = 3
    ) -> RAGResult:
        """带上下文的提问"""
    
    @abstractmethod
    async def search_knowledge(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        """搜索知识库"""
    
    @abstractmethod
    async def add_document(self, document: dict[str, Any]) -> bool:
        """添加文档到知识库"""
    
    @abstractmethod
    async def get_knowledge_stats(self) -> dict[str, Any]:
        """获取知识库统计信息"""
    
    @abstractmethod
    async def is_available(self) -> bool:
        """检查知识库是否可用"""


class IEvaluationService(ABC):
    """评估服务接口"""
    
    @abstractmethod
    async def evaluate_response(
        self,
        user_message: str,
        bot_response: str,
        context: dict[str, Any]
    ) -> dict[str, Any]:
        """评估回复质量"""
    
    @abstractmethod
    async def get_evaluation_history(
        self,
        user_id: str,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """获取评估历史"""
    
    @abstractmethod
    async def get_performance_metrics(self) -> dict[str, Any]:
        """获取性能指标"""


class IFeedbackService(ABC):
    """反馈服务接口"""
    
    @abstractmethod
    async def submit_feedback(
        self,
        user_id: str,
        session_id: str,
        feedback_type: str,
        content: str,
        rating: int | None = None
    ) -> str:
        """提交反馈"""
    
    @abstractmethod
    async def get_feedback(
        self,
        user_id: str | None = None,
        feedback_type: str | None = None,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """获取反馈"""
    
    @abstractmethod
    async def analyze_feedback(self, feedback_id: str) -> dict[str, Any]:
        """分析反馈"""


class IDatabaseService(ABC):
    """数据库服务接口"""
    
    @abstractmethod
    async def connect(self) -> bool:
        """连接数据库"""
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开数据库连接"""
    
    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
    
    @abstractmethod
    async def execute_query(self, query: str, params: dict[str, Any]) -> Any:
        """执行查询"""
    
    @abstractmethod
    async def execute_transaction(self, operations: list[dict[str, Any]]) -> bool:
        """执行事务"""


class ILogger(ABC):
    """日志服务接口"""
    
    @abstractmethod
    async def debug(self, message: str, **kwargs) -> None:
        """调试日志"""
    
    @abstractmethod
    async def info(self, message: str, **kwargs) -> None:
        """信息日志"""
    
    @abstractmethod
    async def warning(self, message: str, **kwargs) -> None:
        """警告日志"""
    
    @abstractmethod
    async def error(self, message: str, exception: Exception | None = None, **kwargs) -> None:
        """错误日志"""
    
    @abstractmethod
    async def critical(self, message: str, exception: Exception | None = None, **kwargs) -> None:
        """严重错误日志"""


class IValidationService(ABC):
    """验证服务接口"""
    
    @abstractmethod
    async def validate_request(self, request: dict[str, Any]) -> tuple[bool, list[str]]:
        """验证请求"""
    
    @abstractmethod
    async def validate_user_input(self, text: str) -> tuple[bool, list[str]]:
        """验证用户输入"""
    
    @abstractmethod
    async def sanitize_input(self, text: str) -> str:
        """清理输入"""
