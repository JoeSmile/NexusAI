"""数据库模块 — pgvector + SQLAlchemy

约定:
- 新代码 / 向量检索: `from backend.database.pgvector_session import ChatMessage, Base, ...`
- 旧 DatabaseManager ORM: `from backend.database.legacy import ...`（包级 ChatMessage/Base 仍指向 legacy，避免打断现有调用方）
- 明确别名: VectorBase / VectorChatMessage / VectorChatSession
"""

from backend.database.legacy import (  # noqa: F401
    ABTestEvent,
    ABTestExperiment,
    ABTestGroupAssignment,
    DATABASE_URL,
    Base,
    Base as LegacyBase,
    ChatMessage,
    ChatMessage as LegacyChatMessage,
    ChatSession,
    ChatSession as LegacyChatSession,
    DatabaseManager,
    EmotionAnalysis,
    Knowledge,
    MemoryItem,
    ResponseEvaluation,
    SessionLocal,
    SystemLog,
    User,
    UserFeedback,
    UserPersonalization,
    UserProfileDB,
    _resolve_database_url,
    create_tables,
    engine,
    get_db,
)
from backend.database.pgvector_session import (  # noqa: F401
    Base as VectorBase,
    ChatMessage as VectorChatMessage,
    ChatSession as VectorChatSession,
    PGVectorSession,
    get_pg_session,
)

__all__ = [
    "ABTestEvent",
    "ABTestExperiment",
    "ABTestGroupAssignment",
    "DATABASE_URL",
    "Base",
    "ChatMessage",
    "ChatSession",
    "DatabaseManager",
    "EmotionAnalysis",
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
]
