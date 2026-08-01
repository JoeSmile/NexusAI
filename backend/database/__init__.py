"""数据库模块 — pgvector + SQLAlchemy

约定:
- 会话/消息/记忆/权限等主模型: `backend.database.pgvector_session`
- 次级模型 + 引擎引导: `backend.database.models`
- engine / SessionLocal / DATABASE_URL 惰性导出（Task 19.01）
"""

from backend.database.models import (
    ABTestEvent,
    ABTestExperiment,
    ABTestGroupAssignment,
    Base,
    DatabaseManager,
    Knowledge,
    MemoryItem,
    ResponseEvaluation,
    SystemLog,
    User,
    UserFeedback,
    UserPersonalization,
    UserProfileDB,
    _resolve_database_url,
    create_tables,
    get_db,
    get_session,
    init_database,
)
from backend.database.models import (
    Base as ModelsBase,
)
from backend.database.pgvector_session import (
    Base as VectorBase,
)
from backend.database.pgvector_session import (
    ChatMessage,
    ChatSession,
    PGVectorSession,
    get_pg_session,
)

__all__ = [
    "DATABASE_URL",
    "ABTestEvent",
    "ABTestExperiment",
    "ABTestGroupAssignment",
    "Base",
    "ChatMessage",
    "ChatSession",
    "DatabaseManager",
    "Knowledge",
    "MemoryItem",
    "ModelsBase",
    "PGVectorSession",
    "ResponseEvaluation",
    "SessionLocal",
    "SystemLog",
    "User",
    "UserFeedback",
    "UserPersonalization",
    "UserProfileDB",
    "VectorBase",
    "_resolve_database_url",
    "create_tables",
    "engine",
    "get_db",
    "get_pg_session",
    "get_session",
    "init_database",
]


def __getattr__(name: str):
    """惰性转发 engine / SessionLocal / DATABASE_URL。"""
    if name in ("engine", "SessionLocal", "DATABASE_URL"):
        from backend.database import models as _models

        return getattr(_models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
