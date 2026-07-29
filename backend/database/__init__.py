"""数据库模块 — pgvector + SQLAlchemy

向后兼容：从 legacy 再导出 DatabaseManager 与旧 ORM。
"""

from backend.database.legacy import (  # noqa: F401
    ABTestEvent,
    ABTestExperiment,
    ABTestGroupAssignment,
    DATABASE_URL,
    Base,
    ChatMessage,
    ChatSession,
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
    "MemoryItem",
    "PGVectorSession",
    "ResponseEvaluation",
    "SessionLocal",
    "SystemLog",
    "User",
    "UserFeedback",
    "UserPersonalization",
    "UserProfileDB",
    "_resolve_database_url",
    "create_tables",
    "engine",
    "get_db",
    "get_pg_session",
]
