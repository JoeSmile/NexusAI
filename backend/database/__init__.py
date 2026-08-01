"""数据库模块 — pgvector + SQLAlchemy

约定:
- 新代码 / 向量检索: `from backend.database.pgvector_session import ChatMessage, Base, ...`
- 旧 DatabaseManager ORM: `from backend.database.legacy import ...`
- engine / SessionLocal / DATABASE_URL 惰性导出（Task 19.01）
"""

from backend.database.legacy import (
    ABTestEvent,
    ABTestExperiment,
    ABTestGroupAssignment,
    Base,
    ChatMessage,
    ChatSession,
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
from backend.database.legacy import (
    Base as LegacyBase,
)
from backend.database.legacy import (
    ChatMessage as LegacyChatMessage,
)
from backend.database.legacy import (
    ChatSession as LegacyChatSession,
)
from backend.database.pgvector_session import (
    Base as VectorBase,
)
from backend.database.pgvector_session import (
    ChatMessage as VectorChatMessage,
)
from backend.database.pgvector_session import (
    ChatSession as VectorChatSession,
)
from backend.database.pgvector_session import (
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
    "LegacyBase",
    "LegacyChatMessage",
    "LegacyChatSession",
    "MemoryItem",
    "PGVectorSession",
    "ResponseEvaluation",
    "SessionLocal",
    "SystemLog",
    "User",
    "UserFeedback",
    "UserPersonalization",
    "UserProfileDB",
    "VectorBase",
    "VectorChatMessage",
    "VectorChatSession",
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
        from backend.database import legacy as _legacy

        return getattr(_legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
