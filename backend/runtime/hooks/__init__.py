"""
Hooks — 生命周期钩子系统

支持 pre/post LLM call、tool failure 等生命周期事件注入。
"""

from backend.runtime.hooks.base import (
    HookContext,
    HookDispatcher,
    PluginHook,
    ToolFailureContext,
)

__all__ = [
    "HookContext",
    "HookDispatcher",
    "PluginHook",
    "ToolFailureContext",
]
