"""
pgvector 数据库会话管理 + ORM 模型。

所有模型继承 Base，统一管理。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    user_id = Column(String(100), nullable=False, index=True)
    title = Column(Text)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    session_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_messages_tenant_session", "tenant_id", "session_id"),
    )


class UserMemory(Base):
    __tablename__ = "user_memories"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    user_id = Column(String(100), nullable=False, index=True)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    source = Column(String(50), default="extracted")
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "key"),)


class ColdMemory(Base):
    __tablename__ = "cold_memories"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    user_id = Column(String(100), nullable=False, index=True)
    session_id = Column(String(100))
    summary = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    trace_id = Column(String(100))
    input_text = Column(Text)
    output_text = Column(Text)
    model = Column(String(100), default="")
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    error_code = Column(String(50))
    ip_address = Column(String(50), default="")
    user_agent = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("idx_audit_tenant_time", "tenant_id", "created_at"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)
    key_prefix = Column(String(8))
    role = Column(String(32), nullable=False, default="user")
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    description = Column(Text, default="")
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    access_key_id = Column(String(64), unique=True, nullable=True)
    access_key_secret = Column(Text, nullable=True)
    signature_enabled = Column(Boolean, default=False)
    signature_key_version = Column(Integer, default=1)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(32), unique=True, nullable=False)
    permissions = Column(JSON, nullable=False)
    description = Column(Text, default="")


class UserAppPerm(Base):
    __tablename__ = "user_app_perms"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False)
    user_id = Column(String(100), nullable=False)
    permissions = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(128), nullable=False)
    resource = Column(String(256), nullable=False)
    resource_type = Column(String(32), nullable=False, default="permission")
    action = Column(String(64), nullable=False)
    params = Column(JSON, default=dict)
    status = Column(String(16), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    timeout_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_reason = Column(Text, nullable=True)
    __table_args__ = (
        Index("idx_apr_tenant_status", "tenant_id", "status"),
    )


class CacheEntry(Base):
    __tablename__ = "cache_entries"
    id = Column(Integer, primary_key=True)
    cache_key = Column(String(256), unique=True, nullable=False, index=True)
    cache_type = Column(String(20), nullable=False)
    tenant_id = Column(String(50), nullable=False)
    value = Column(Text, nullable=False)
    ttl_seconds = Column(Integer, default=300)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class TenantConfig(Base):
    __tablename__ = "tenant_config"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), unique=True, nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LlmApiKey(Base):
    __tablename__ = "llm_api_keys"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    key_alias = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)
    base_url = Column(String(256), default="")
    encrypted_key = Column(Text, nullable=False)
    key_version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    last_verified = Column(DateTime, nullable=True)
    last_verified_ok = Column(Boolean, nullable=True)
    last_failed_at = Column(DateTime, nullable=True)  # Task 27: 冷却依据
    consecutive_failures = Column(Integer, default=0, nullable=False)  # Task 27: 摘除依据
    description = Column(Text, default="")
    created_by = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow)
    rotated_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "key_alias"),
        Index("idx_lak_tenant", "tenant_id", "is_active"),
    )


class KnowledgeChunk(Base):
    """RAG 知识块 — 替代 Chroma knowledge collection"""

    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    category = Column(String(100), default="general", index=True)
    content = Column(Text, nullable=False)
    source = Column(String(256), default="")
    source_type = Column(String(32), default="text", index=True)  # text|pdf|audio|image
    meta = Column(JSON, default=dict)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PGVectorSession:
    """pgvector 数据库会话管理器"""

    def __init__(self, db_url: str | None = None):
        if db_url is None:
            from backend.database.models import _resolve_database_url

            db_url = _resolve_database_url()
        self.engine = create_engine(db_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

    def init_db(self):
        """创建所有表（仅首次部署使用）并种子角色"""
        Base.metadata.create_all(self.engine)
        self._seed_roles()

    def _seed_roles(self) -> None:
        """幂等写入默认角色"""
        from backend.core.auth.models import ROLES

        with self.Session() as session:
            for name, meta in ROLES.items():
                existing = session.query(Role).filter_by(name=name).first()
                if existing:
                    continue
                session.add(
                    Role(
                        name=name,
                        permissions=list(meta.get("permissions", [])),
                        description=str(meta.get("description", "")),
                    )
                )
            session.commit()

    @contextmanager
    def get_session(self):
        """上下文管理器获取 session"""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def query_with_tenant(
        self,
        model_class,
        tenant_id: str,
        user_id: str | None = None,
    ):
        """带租户隔离的查询 — 自动加 WHERE tenant_id=:tid（可选 user_id）"""
        with self.Session() as session:
            q = session.query(model_class).filter(model_class.tenant_id == tenant_id)
            if user_id and hasattr(model_class, "user_id"):
                q = q.filter(model_class.user_id == user_id)
            rows = q.all()
            session.expunge_all()
            return rows

    def search_similar(
        self,
        tenant_id: str,
        embedding: list[float],
        limit: int = 5,
        min_score: float = 0.7,
    ) -> list[ChatMessage]:
        """ANN 检索相似消息"""
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        with self.Session() as session:
            sql = text(
                """
                SELECT id, tenant_id, session_id, user_id, role, content, created_at,
                       1 - (embedding <=> :vec::vector) AS similarity
                FROM chat_messages
                WHERE tenant_id = :tid
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> :vec::vector) >= :min_score
                ORDER BY embedding <=> :vec::vector
                LIMIT :lim
                """
            )
            rows = session.execute(
                sql,
                {
                    "vec": vec_str,
                    "tid": tenant_id,
                    "min_score": min_score,
                    "lim": limit,
                },
            ).fetchall()
            return [
                ChatMessage(
                    id=r.id,
                    tenant_id=r.tenant_id,
                    session_id=r.session_id,
                    user_id=r.user_id,
                    role=r.role,
                    content=r.content,
                    created_at=r.created_at,
                )
                for r in rows
            ]


_pg_session: PGVectorSession | None = None


def get_pg_session() -> PGVectorSession:
    global _pg_session
    if _pg_session is None:
        _pg_session = PGVectorSession()
    return _pg_session
