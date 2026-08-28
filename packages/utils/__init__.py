"""
工具模块
包含各种实用工具和辅助函数
"""

from .decorators import cache, log_execution, rate_limit, retry, validate_input
from .dependency_injection import Container, Dependency, Singleton, Transient
from .formatters import format_error, format_response, format_timestamp
from .helpers import (
    calculate_similarity,
    generate_id,
    merge_dicts,
    sanitize_text,
)
from .validators import (
    validate_email,
    validate_phone,
    validate_session_id,
    validate_text_length,
    validate_user_id,
)

__all__ = [
    # 依赖注入
    "Container",
    "Dependency",
    "Singleton",
    "Transient",
    
    # 装饰器
    "retry",
    "rate_limit",
    "cache",
    "validate_input",
    "log_execution",
    
    # 验证器
    "validate_email",
    "validate_phone",
    "validate_text_length",
    "validate_session_id",
    "validate_user_id",
    
    # 格式化器
    "format_response",
    "format_error",
    "format_timestamp",
    
    # 辅助函数
    "generate_id",
    "sanitize_text",
    "calculate_similarity",
    "merge_dicts"
]
