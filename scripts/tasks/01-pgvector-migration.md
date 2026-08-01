# Task 01: pgvector 迁移

> ⚠️ embedding 列用 `pgvector.sqlalchemy.Vector(1536)`，**不是** `ARRAY(Float)`。
> 老 `DatabaseManager` 标记 `# DEPRECATED`，不动。
> **前置依赖:** `tasks/00-rebranding.md`（必须先改完项目名）
> **完成后:** 执行 `tasks/02-auth-rbac.md`

## Subtask 01.01: pyproject.toml 依赖

**移除:** `PyMySQL`, `chromadb`, `langchain-chroma`, `sentence-transformers`, `transformers`
**添加:** `psycopg2-binary>=2.9.0`, `sqlalchemy-pgvector>=0.7.0`, `pgvector>=0.3.0`
**运行:** `uv lock && uv sync`

## Subtask 01.02: SQLAlchemy 模型

**文件:** `backend/database/pgvector_session.py`
**定义:** `Base`, `ChatMessage`, `ChatSession`, `UserMemory`, `ColdMemory`, `AuditLog`, `ApiKey`, `Role`, `UserAppPerm`, `ApprovalRequest`, `CacheEntry`

关键模型:
```python
from pgvector.sqlalchemy import Vector

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    session_id = Column(String(100), nullable=False)
    user_id = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    emotion = Column(String(50))
    emotion_intensity = Column(Float, default=5.0)
    embedding = Column(Vector(1536), nullable=True)  # ✅ pgvector
    created_at = Column(DateTime, default=datetime.utcnow)
```

## Subtask 01.03: PGVectorSession

**文件:** `backend/database/pgvector_session.py`
- `__init__(db_url)` — create_engine + sessionmaker
- `search_similar(tenant_id, embedding, limit=5)` — ANN 检索用 `cosine_distance`
- `get_session()` — 上下文管理器

```python
class PGVectorSession:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)

    def search_similar(self, tenant_id, embedding, limit=5):
        with self.Session() as session:
            return session.query(ChatMessage).filter(
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.embedding.isnot(None),
            ).order_by(
                ChatMessage.embedding.cosine_distance(embedding)
            ).limit(limit).all()
```

## Subtask 01.04: vector_ops.py

**文件:** `backend/database/vector_ops.py`
- `store_embedding(message_id, embedding)`
- `search_memories(tenant_id, query_vec, limit)`
- `delete_expired_entries(ttl_hours)`

## Subtask 01.05: database.py 适配

**文件:** `backend/database.py`
- `_resolve_database_url()` 加 `DB_TYPE=postgresql` 分支
- 老 `DatabaseManager` 加 `# DEPRECATED`
- 新增 `get_pg_session()` 快捷函数

## 验证

```bash
uv run python -c "from pgvector.sqlalchemy import Vector; print('✅ pgvector ok')"
uv run python -c "from backend.database.pgvector_session import PGVectorSession; print('✅ session ok')"
```
