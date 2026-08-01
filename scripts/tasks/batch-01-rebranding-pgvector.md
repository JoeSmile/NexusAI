# Batch 1: 基建 — Rebranding + pgvector 迁移

> **包含:** Task 00 (5 subtasks) + Task 01 (5 subtasks) = 10 subtasks
> **预估:** 40-60 分钟
> **Commit:** `git add -A && git commit -m "feat: rebrand to ContextGate + pgvector migration\n\nSigned-off-by: Joe"`

---

## A. Task 00: Rebranding — ContextGate

### 00.1 项目元数据

**文件:** `pyproject.toml`

```toml
[project]
name = "context-gate"
description = "The Intelligent Gateway for LLM Context Management"
authors = [{name = "Joe"}]
keywords = ["llm-gateway", "context-management", "observability", "ai-gateway"]

[project.urls]
Homepage = "https://github.com/joe/context-gate"
Repository = "https://github.com/joe/context-gate"
```

---

### 00.2 后端代码脱敏

**文件:** `backend/app.py`

修改 3 处：

```python
# 第 94-97 行: FastAPI title/description
app = FastAPI(
    title="ContextGate API",
    description="The Intelligent Gateway for LLM Context Management",
    version="1.0.0",  # 3.0.0 → 1.0.0
    docs_url="/docs",
    redoc_url="/redoc"
)

# 第 209 行: root() 返回值
return {
    "name": "ContextGate",
    "version": "1.0.0",
    "status": "running",
    # ... 其余保持
}

# 第 230 行: health_check() 返回值
"version": "1.0.0",
```

**文件:** `backend/routers/chat.py` — 第 27 行 tag

```python
@router.post("/chat", tags=["chat"])
```

**文件:** `backend/routers/memory.py` — tag

```python
@router.get("/memory", tags=["memory"])
```

**文件:** `backend/routers/emotion_analysis.py` — tag

```python
@router.post("/emotion", tags=["analysis"])
```

**文件:** `backend/routers/feedback.py` — tag

```python
@router.post("/feedback", tags=["feedback"])
```

**文件:** `backend/routers/agent.py` — tag

```python
@router.post("/agent", tags=["agent"])
```

**文件:** `backend/modules/llm/core/llm_core.py`

```python
# 类名重命名
class ChatEngine:  # 原来是 SimpleEmotionalChatEngine
    ...
```

**文件:** `backend/modules/llm/core/llm_with_plugins.py`

```python
class ChatEngineWithTools:  # 原来是 EmotionalChatEngineWithPlugins
    ...
```

**文件:** `backend/xinyu_prompt.py` — 删除文件中所有包含"心语"的字符串

```python
# 搜索替换: 心语 → ContextGate
# 搜索替换: 情感陪伴 → LLM Gateway
```

**文件:** `config.py` — 第 13 行去情感化

```python
# 原来可能是情感相关的配置描述，改为通用描述
```

---

### 00.3 README 重写

**文件:** `README.md`

```markdown
# ContextGate

> The Intelligent Gateway for LLM Context Management

企业级 LLM 前置处理管线，支持认证、多租户、安全护栏、可观测、模型路由、缓存。

## Quick Start

```bash
# 1. 启动基础设施
docker compose -f docker-compose.local.yml up -d

# 2. 安装依赖
uv sync

# 3. 初始化数据库
uv run python -c "from backend.database.pgvector_session import PGVectorSession; PGVectorSession().init_db()"

# 4. 创建 API Key
uv run python scripts/seed_api_keys.py

# 5. 启动服务
uv run uvicorn backend.app:app --reload
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## License

Apache 2.0
```

---

### 00.4 Docker 配置改名

**文件:** `docker-compose.yml` — service name

```yaml
services:
  contextgate:  # 原来是 backend
    build: .
    ...
```

**文件:** `docker-compose.local.yml`

```yaml
services:
  contextgate:  # 原来是 backend
    build: .
    ...
```

**文件:** `monitoring/prometheus.yml`

```yaml
scrape_configs:
  - job_name: 'contextgate'  # 原来是 backend
    ...
```

---

### 00.5 前端保留不动

不需要修改任何 `frontend/` 目录文件。

---

## B. Task 01: pgvector 迁移

### 01.01 pyproject.toml 依赖更新

**文件:** `pyproject.toml`

```toml
[project]
dependencies = [
    "psycopg2-binary>=2.9.0",
    "sqlalchemy-pgvector>=0.7.0",
    "pgvector>=0.3.0",
    # 移除: PyMySQL, chromadb, langchain-chroma, sentence-transformers, transformers
    # 保留其他已有依赖
]
```

> ⚠️ **Cursor 注意:** 不要删除 LangChain 相关依赖（langgraph, langfuse 等后续用）。只删 PyMySQL, chromadb, langchain-chroma, sentence-transformers, transformers。

---

### 01.02 SQLAlchemy 模型

**创建:** `backend/database/__init__.py`

```python
"""数据库模块 — pgvector + SQLAlchemy"""
```

**创建:** `backend/database/pgvector_session.py`

```python
"""
pgvector 数据库会话管理 + ORM 模型。

所有模型继承 Base，统一管理。
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float,
    DateTime, Boolean, ForeignKey, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from pgvector.sqlalchemy import Vector

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
    emotion = Column(String(50))
    emotion_intensity = Column(Float, default=5.0)
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
    emotion_tags = Column(JSON)
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
    key_prefix = Column(String(8))  # 前 8 位用于识别
    role = Column(String(32), nullable=False, default="user")
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    description = Column(Text, default="")
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    # 签名认证字段（Task 18 加密存储）
    access_key_id = Column(String(64), unique=True, nullable=True)
    access_key_secret = Column(Text, nullable=True)
    signature_enabled = Column(Boolean, default=False)
    signature_key_version = Column(Integer, default=1)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(32), unique=True, nullable=False)
    permissions = Column(JSON, nullable=False)  # ["chat:write", "admin:*", ...]
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
    cache_type = Column(String(20), nullable=False)  # "exact" | "template"
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
    description = Column(Text, default="")
    created_by = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow)
    rotated_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "key_alias"),
        Index("idx_lak_tenant", "tenant_id", "is_active"),
    )
```

---

### 01.03 PGVectorSession

**追加写入** `backend/database/pgvector_session.py`（在模型定义下面）

```python
class PGVectorSession:
    """pgvector 数据库会话管理器"""

    def __init__(self, db_url: str | None = None):
        if db_url is None:
            from backend.database import _resolve_database_url
            db_url = _resolve_database_url()
        self.engine = create_engine(db_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

    def init_db(self):
        """创建所有表（仅首次部署使用）"""
        Base.metadata.create_all(self.engine)

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

    def search_similar(
        self, tenant_id: str, embedding: list[float],
        limit: int = 5, min_score: float = 0.7
    ) -> list[ChatMessage]:
        """ANN 检索相似消息"""
        from sqlalchemy import text
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        with self.Session() as session:
            sql = text("""
                SELECT id, tenant_id, session_id, user_id, role, content,
                       emotion, emotion_intensity, created_at,
                       1 - (embedding <=> :vec::vector) AS similarity
                FROM chat_messages
                WHERE tenant_id = :tid
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> :vec::vector) >= :min_score
                ORDER BY embedding <=> :vec::vector
                LIMIT :lim
            """)
            rows = session.execute(sql, {
                "vec": vec_str, "tid": tenant_id,
                "min_score": min_score, "lim": limit,
            }).fetchall()
            return [ChatMessage(
                id=r.id, tenant_id=r.tenant_id, session_id=r.session_id,
                user_id=r.user_id, role=r.role, content=r.content,
                emotion=r.emotion, emotion_intensity=r.emotion_intensity,
                created_at=r.created_at,
            ) for r in rows]


# 全局单例
_pg_session: PGVectorSession | None = None


def get_pg_session() -> PGVectorSession:
    global _pg_session
    if _pg_session is None:
        _pg_session = PGVectorSession()
    return _pg_session
```

---

### 01.04 vector_ops.py

**创建:** `backend/database/vector_ops.py`

```python
"""向量操作封装 — 存储/检索/过期清理"""

from datetime import datetime, timedelta
from backend.database.pgvector_session import get_pg_session, ChatMessage


def store_embedding(message_id: int, embedding: list[float]) -> None:
    """存储消息的 embedding"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        msg = session.query(ChatMessage).filter_by(id=message_id).first()
        if msg:
            msg.embedding = embedding
            session.commit()


def search_memories(
    tenant_id: str, query_vec: list[float],
    limit: int = 5, min_score: float = 0.7
) -> list[dict]:
    """搜索相似记忆"""
    session_factory = get_pg_session()
    results = session_factory.search_similar(
        tenant_id=tenant_id, embedding=query_vec,
        limit=limit, min_score=min_score,
    )
    return [
        {
            "id": r.id,
            "content": r.content,
            "role": r.role,
            "emotion": r.emotion,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ]


def delete_expired_entries(ttl_hours: int = 24) -> int:
    """删除过期缓存条目"""
    from backend.database.pgvector_session import CacheEntry
    session_factory = get_pg_session()
    cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
    with session_factory.Session() as session:
        deleted = session.query(CacheEntry).filter(
            CacheEntry.created_at < cutoff
        ).delete()
        session.commit()
        return deleted
```

---

### 01.05 database.py 适配

**修改:** `backend/database.py`

```python
# 在文件顶部添加以下函数
import os


def _resolve_database_url() -> str:
    """解析数据库连接 URL"""
    db_type = os.getenv("DB_TYPE", "postgresql")
    if db_type == "sqlite":
        return os.getenv("DATABASE_URL", "sqlite:///./data/emotional_chat.db")
    # 默认 postgresql + pgvector
    return os.getenv(
        "DATABASE_URL",
        "postgresql://emotional_chat:emotional_chat_password@localhost:5432/emotional_chat"
    )


# 在文件底部，老的 DatabaseManager 类之前加
# DEPRECATED: 请使用 backend.database.pgvector_session.PGVectorSession
```

> ⚠️ **Cursor 注意:** 不要删除老 `DatabaseManager`，只加 `# DEPRECATED` 标记。老代码可能还在被引用。

---

## 验证

```bash
# 1. 检查无"心语"字眼
grep -r "心语\|情感陪伴" backend/ --include="*.py" || echo "✅ 无情感化字眼"

# 2. 检查项目名已改
grep "name.*=.*emotional-chat" pyproject.toml && echo "❌ 还有 emotional-chat" || echo "✅ 项目名已改"

# 3. 验证 pgvector 模型可导入
uv run python -c "
from backend.database.pgvector_session import PGVectorSession, get_pg_session
from pgvector.sqlalchemy import Vector
print('✅ pgvector 模型导入成功')
print(f'  ORM models: ChatMessage, ApiKey, AuditLog, ...')
"

# 4. 验证 vector_ops
uv run python -c "
from backend.database.vector_ops import store_embedding, search_memories, delete_expired_entries
print('✅ vector_ops 导入成功')
"

# 5. 验证 database.py 适配
uv run python -c "
from backend.database import _resolve_database_url
url = _resolve_database_url()
print(f'✅ database URL resolved: {url}')
"
```
