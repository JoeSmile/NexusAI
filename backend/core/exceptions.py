#!/usr/bin/env python3
"""
异常处理模块
定义系统的自定义异常类
"""

from typing import Any


class ContextGateException(Exception):
    """ContextGate机器人基础异常类"""
    
    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details
        }


class ConfigurationError(ContextGateException):
    """配置错误"""


class DatabaseError(ContextGateException):
    """数据库错误"""


class RAGError(ContextGateException):
    """RAG知识库错误"""


class ValidationError(ContextGateException):
    """验证错误"""
    
    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: Any | None = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.field = field
        self.value = value
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        result = super().to_dict()
        if self.field:
            result["field"] = self.field
        if self.value is not None:
            result["value"] = str(self.value)
        return result


class AuthenticationError(ContextGateException):
    """认证错误"""


class AuthorizationError(ContextGateException):
    """授权错误"""


class RateLimitError(ContextGateException):
    """频率限制错误"""
    
    def __init__(
        self,
        message: str = "请求频率过高",
        retry_after: int | None = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        result = super().to_dict()
        if self.retry_after:
            result["retry_after"] = self.retry_after
        return result


class ExternalServiceError(ContextGateException):
    """外部服务错误"""
    
    def __init__(
        self,
        message: str,
        service_name: str,
        status_code: int | None = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.service_name = service_name
        self.status_code = status_code
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        result = super().to_dict()
        result["service_name"] = self.service_name
        if self.status_code:
            result["status_code"] = self.status_code
        return result


class MemoryError(ContextGateException):
    """记忆系统错误"""



class ContextError(ContextGateException):
    """上下文管理错误"""


class ChatError(ContextGateException):
    """聊天服务错误"""


class EvaluationError(ContextGateException):
    """评估系统错误"""


class FeedbackError(ContextGateException):
    """反馈系统错误"""


class AgentError(ContextGateException):
    """Agent系统错误"""


# 异常处理器映射
EXCEPTION_HANDLERS = {
    ConfigurationError: lambda e: (400, {"error": "配置错误", "details": e.message}),
    ValidationError: lambda e: (422, {"error": "验证错误", "details": e.to_dict()}),
    AuthenticationError: lambda e: (401, {"error": "认证失败", "details": e.message}),
    AuthorizationError: lambda e: (403, {"error": "权限不足", "details": e.message}),
    RateLimitError: lambda e: (429, {"error": "请求过于频繁", "details": e.to_dict()}),
    DatabaseError: lambda e: (500, {"error": "数据库错误", "details": e.message}),
    ExternalServiceError: lambda e: (503, {"error": "外部服务不可用", "details": e.to_dict()}),
    RAGError: lambda e: (500, {"error": "知识库错误", "details": e.message}),
    MemoryError: lambda e: (500, {"error": "记忆系统错误", "details": e.message}),
    ContextError: lambda e: (500, {"error": "上下文错误", "details": e.message}),
    ChatError: lambda e: (500, {"error": "聊天服务错误", "details": e.message}),
    EvaluationError: lambda e: (500, {"error": "评估系统错误", "details": e.message}),
    FeedbackError: lambda e: (500, {"error": "反馈系统错误", "details": e.message}),
    AgentError: lambda e: (500, {"error": "Agent系统错误", "details": e.message}),
    ContextGateException: lambda e: (500, {"error": "系统错误", "details": e.message}),
}
