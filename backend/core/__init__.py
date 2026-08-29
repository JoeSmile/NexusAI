"""
遗留 re-export：原 backend.core 包入口。

配置真源：根目录 ``config.py``（``get_settings`` / ``Config`` 代理）。
异常真源：``packages.errors``。
"""

from config import Config, get_settings
from packages.errors import ErrorCode, NexusAIException

__all__ = [
    "Config",
    "ErrorCode",
    "NexusAIException",
    "get_settings",
]
