"""
遗留 re-export：原 backend.core 包入口。

真源已迁至 packages.*；保留此模块以免旧 ``from backend.core import …`` 立刻炸。
"""

from packages.config import Config, get_config
from packages.exceptions import (
    ConfigurationError,
    DatabaseError,
    NexusAIException,
    RAGError,
    ValidationError,
)
from packages.interfaces import IChatEngine, IContextService, IMemoryService, IRAGService

__all__ = [
    "Config",
    "ConfigurationError",
    "DatabaseError",
    "NexusAIException",
    "IChatEngine",
    "IContextService",
    "IMemoryService",
    "IRAGService",
    "RAGError",
    "ValidationError",
    "get_config",
]
