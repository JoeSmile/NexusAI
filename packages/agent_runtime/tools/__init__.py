"""
External Tools - 外部工具模块

提供各种外部工具实现：
- 日历API
- 定时提醒服务
- Agent核心工具函数
"""

from .calendar_api import CalendarAPI
from .scheduler_service import SchedulerService


# 延迟导入Agent核心工具函数，避免循环依赖
def __getattr__(name):
    """延迟导入 agent_tools 中的函数"""
    _agent_tools_funcs = [
        "set_daily_reminder",
        "send_follow_up_message"
    ]
    if name in _agent_tools_funcs:
        from . import agent_tools
        return getattr(agent_tools, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CalendarAPI",
    "SchedulerService",
    # Agent核心工具函数（延迟导入）
    "set_daily_reminder",
    "send_follow_up_message"
]

