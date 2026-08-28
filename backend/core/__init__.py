"""
遗留 re-export：原 backend.core 包入口。

真源已迁至 packages.*；保留此模块以免旧 ``from backend.core import …`` 立刻炸。
异常统一用 ``packages.errors``（``ErrorCode`` / ``NexusAIException``）。
"""

from packages.config import Config, get_config
from packages.errors import ErrorCode, NexusAIException
from packages.interfaces import IChatEngine, IContextService, IMemoryService, IRAGService

__all__ = [
    "Config",
    "ErrorCode",
    "NexusAIException",
    "IChatEngine",
    "IContextService",
    "IMemoryService",
    "IRAGService",
    "get_config",
]
