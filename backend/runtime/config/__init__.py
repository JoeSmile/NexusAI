"""
Runtime Config — 模块配置与开关

- ModuleToggles: 每个模块可独立开关
- Guards: 统一的开关检查入口
"""

from backend.runtime.config.guards import ModuleDisabledError, is_module_enabled, require_module
from backend.runtime.config.toggles import ModuleToggles

__all__ = [
    "ModuleDisabledError",
    "ModuleToggles",
    "is_module_enabled",
    "require_module",
]
