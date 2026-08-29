"""
Session — 会话状态管理

提供 6-state FSM 管理会话生命周期，确保状态转换合法可追踪。
包含会话血缘追踪和检查点恢复功能。
"""

from packages.runtime.session.fsm import (
    TERMINAL_STATES,
    IllegalTransitionError,
    SessionFSM,
    SessionState,
)
from packages.runtime.session.lineage import LineageTracker, SessionLineage
from packages.runtime.session.resume import SessionResumer

__all__ = [
    "TERMINAL_STATES",
    "IllegalTransitionError",
    "LineageTracker",
    "SessionFSM",
    "SessionLineage",
    "SessionResumer",
    "SessionState",
]
