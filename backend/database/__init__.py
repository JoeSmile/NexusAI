"""数据库模块 — pgvector + SQLAlchemy

约定:
- 新代码 / 向量检索: `from backend.database.pgvector_session import ChatMessage, Base, ...`
- 旧 DatabaseManager ORM: `from backend.database.legacy import ...`（包级 ChatMessage/Base 仍指向 legacy，避免打断现有调用方）
- 明确别名: VectorBase / VectorChatMessage / VectorChatSession
"""

from backend.database.legacy import (
    DATABASE_URL,
    ABTestEvent,
    ABTestExperiment,
    ABTestGroupAssignment,
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
