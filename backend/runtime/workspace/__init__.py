"""
Workspace — 工作区隔离管理

每个用户/会话有独立的工作区，防止数据竞争。
"""

from backend.runtime.workspace.manager import WorkspaceInfo, WorkspaceManager

__all__ = [
    "WorkspaceInfo",
    "WorkspaceManager",
]
