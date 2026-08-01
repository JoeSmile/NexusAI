# Task 19: 性能瓶颈消除

> **P1 性能 — 当前状况：** 系统在 startup、首次请求、高并发三个场景下存在多处可测量的性能瓶颈。这些瓶颈不解决，LangGraph 管线重构（Task 04）的基准线无法建立，后续优化也无从对比。
> **目标：** 定位并消除模块级延迟、串行阻塞、同步 IO 混入 asyncio、启动时副作用等 9 类瓶颈。每个 subtask 都有可重复的 benchmark 命令。

## 瓶颈全景

| # | 瓶颈 | 类型 | 影响 | 优先级 |
|---|------|------|------|--------|
| 1 | ChromaDB `DefaultEmbeddingFunction()` ONNX 下载 | 启动延迟 | 首次调用阻塞 5-30s | P0 |
| 2 | `database.py` 模块级 pymysql 连接探测 | 启动延迟 | import 时阻塞 3s | P0 |
| 3 | `config.py` 类级 static 求值 | 启动延迟+僵化 | 无法运行时切换 | P1 |
| 4 | `EnhancedContextAssembler` 五步串行 | 请求延迟 | 每请求多花 3-6x 时间 | P1 |
| 5 | `MemoryService._sync_memories_to_db` 逐条提交 | 请求延迟 | 写放大 + SQLAlchemy 事务开销 | P1 |
| 6 | `PerformanceOptimizer` 同步 Redis | 请求延迟 | 阻塞 event loop | P1 |
| 7 | ChatService/EnhancedChatService 上帝对象 | 内存+启动 | 每次创建都初始化整个图 | P1 |
| 8 | `app.py` 模块级 try/except import swamp | 启动延迟 | 所有 import 顺序执行 | P2 |
| 9 | `vector_store.py` 启动时 `shutil.rmtree` 重建 | 启动风险 | 每启动都可能丢数据 | P0 |
| 10 | `database.py` MySQL 无连接池配置 | 高并发 | 高并发连接超载 | P2 |
| 11 | `app.mount("/uploads", StaticFiles)` 未经过 auth | 安全 | 文件无需认证即可访问 | P2 |
| 12 | 所有 `from backend.xxx import ...` 级联 import | 启动延迟+耦合 | 改一个文件触发热重载全链路 | P2 |

## 架构原则

```
改造前                             改造后
───────                            ───────
模块级 import → 副作用             │  惰性初始化 / FastAPI lifespan
同步 DB ←── SQLAlchemy sync        │  asyncpg / aiomysql + 连接池
ChromaDB blocking ONNX 下载         │  embedding lazy init + 预热
串行 context assembly               │  asyncio.gather 并行
逐条 commit                         │  bulk_save + 事务批处理
config.py 静态属性                  │  pydantic-settings + 运行时重载
上帝服务对象                        │  按需注入 + 依赖容器
```

---

## Subtask 19.01: database.py — 消除模块级副作用

> **现状：** `_resolve_database_url()` 在模块作用域执行，包含 `pymysql.connect()` 阻塞调用（3s timeout）。每次 `from backend.database import ...` 都会触发数据库连接探测。

**方案：**

- 将 `DATABASE_URL` / `engine` / `SessionLocal` / `Base` 的创建移到 `init_database()` 函数
- 保留一个 `DatabaseManager` 类作为惰性入口，首次 `__enter__` 时初始化
- 模块顶层只导出类型定义（模型类、Base）

**修改文件：** `backend/database.py`

```python
# ── 模块顶层：只声明类型，不做任何 IO ──────────────────
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

# Base 和模型类正常定义（它们不需要 DB 连接）
Base = declarative_base()
# ... User, ChatSession, ChatMessage, etc ...

# ── 惰性初始化函数 ─────────────────────────────────────
_engine: "Engine | None" = None
_session_factory: "sessionmaker | None" = None


def init_database(url: str | None = None):
    """首次调用时创建 engine 和 SessionLocal。可在 lifespan 中调用。"""
    global _engine, _session_factory

    if _engine is not None:
        return  # 已初始化

    resolved = url or _resolve_database_url()
    kwargs: dict = {"echo": False}

    if resolved.startswith("sqlite"):
        kwargs.setdefault("connect_args", {}).update(
            {"check_same_thread": False}
        )
    else:
        kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "10"))
        kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "20"))
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "3600"))

    _engine = create_engine(resolved, **kwargs)
    _session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=_engine
    )
    logger.info("database initialized: %s", resolved[:50])


def get_session() -> "Session":
    """惰性获取 session — 业务代码调用时自动 init。"""
    init_database()
    return _session_factory()


class DatabaseManager:
    """保持旧接口兼容：with DatabaseManager() as db:"""
    def __enter__(self):
        self.session = get_session()
        return self

    def __exit__(self, *args):
        if self.session:
            self.session.close()

    @property
    def db(self):
        return self.session
```

**改造引用的模块：** 涉及的所有 `from backend.database import engine, SessionLocal` → 改调 `get_session()`。

**⚠️ Cursor 警告：**
- 当前代码中同时存在 `from backend.database import engine`、`from backend.database import SessionLocal`、和 `with DatabaseManager() as db` 三种模式 — 需要**逐个搜索**替换
- 模型类的 `metadata.create_all(engine)` 需要在调用 `init_database()` 后执行，放在 lifespan 中
- `_resolve_database_url()` 内部 `pymysql.connect()` try 依然存在，但只在首次 `init_database()` 时才执行

**验证：**
```bash
# 1. 不设置任何 DATABASE_URL，确认不阻塞
time python -c "from backend.database import ChatMessage; print('no-block OK')"
# → <1s 返回，不应有 3s 延迟

# 2. 设置后连接正常
USE_SQLITE=1 python -c "
from backend.database import init_database, get_session
init_database()
s = get_session()
print('connected:', s.bind.url)
"
```

---

## Subtask 19.02: VectorStore — 消除启动时 ONNX 下载 + 破坏性重建

> **现状：** `VectorStore.__init__` 中 `DefaultEmbeddingFunction()` 会在首次调用时从 HuggingFace 下载 ONNX 模型（5-30s）。同时启动时如果 schema 不匹配（ChromaDB 版本升级常见），会 `shutil.rmtree()` 删除整个数据库目录。

**修改文件：** `backend/vector_store.py`

```python
import warnings
from functools import cached_property


class VectorStore:
    # ── 禁用 DefaultEmbeddingFunction 自动下载 ──────
    # 改为手动指定轻量 embedding，避免首次请求时 ONNX 下载
    EMBEDDING_MODEL = os.getenv(
        "VECTOR_EMBEDDING_MODEL",
        "all-MiniLM-L6-v2"  # 轻量，~80MB，下载一次后本地缓存
    )
    # 或在配置中允许绕过（对无向量需求的环境）
    EMBEDDING_DISABLED = (
        os.getenv("VECTOR_EMBEDDING_DISABLED", "0").strip() in ("1", "true", "yes")
    )

    def __init__(self):
        self._db_path = Config.CHROMA_PERSIST_DIRECTORY

        # 不做 schema 探测 — ChromaDB 自己会处理版本迁移
        self._settings = Settings(
            anonymized_telemetry=False,
            allow_reset=False,           # ← 禁止自动重建
        )
        self._client: chromadb.PersistentClient | None = None
        self._collections: dict[str, Any] = {}

    def _lazy_client(self):
        if self._client is None:
            os.makedirs(self._db_path, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self._db_path,
                settings=self._settings,
            )
        return self._client

    @cached_property
    def _embedding_fn(self):
        if self.EMBEDDING_DISABLED:
            return None  # 走 ChromaDB 默认（首次可能下载 ONNX）
        from chromadb.utils import embedding_functions
        # ONNX 模型只在首次运行时下载一次，后续从 cache 加载
        # 可通过设置 SENTENCE_TRANSFORMERS_HOME 控制缓存路径
        return embedding_functions.DefaultEmbeddingFunction()

    def _get_or_create_collection(self, name: str):
        if name not in self._collections:
            try:
                col = self._lazy_client().get_or_create_collection(
                    name=name,
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                # 不再 rmtree！改为只读模式 + warn
                logger.warning(
                    "ChromaDB 集合 %s 访问失败（schema 不兼容？），"
                    "降级为 memory-only 模式。运行 chroma migrate 修复。",
                    name,
                )
                col = chromadb.Client(
                    settings=Settings(anonymized_telemetry=False)
                ).get_or_create_collection(
                    name=name,
                    metadata={"hnsw:space": "cosine"},
                )
            self._collections[name] = col
        return self._collections[name]
```

**⚠️ Cursor 警告：**
- 移除 `shutil.rmtree()` 后，如果确实存在 ChromaDB 版本不兼容，会回退到 memory-only 模式。需要一个 `chroma migrate` 脚本来修复持久化数据库
- `DefaultEmbeddingFunction()` 内部使用 `sentence-transformers` 的 ONNX 模型，首次调用时下载 ~80MB。通过 `VECTOR_EMBEDDING_MODEL` env 控制模型名称
- `cached_property` 是 Python 3.8+ 的 `functools` 特性，不需要 `@property`

**验证：**
```bash
# 1. 启动不触发 ONNX 下载（手工断开网络也能启动）
VECTOR_EMBEDDING_DISABLED=1 python -c "
from backend.vector_store import VectorStore
vs = VectorStore()
print('vector store created (no download)')
"

# 2. 首次调用触发 lazy init
python -c "
from backend.vector_store import VectorStore
vs = VectorStore()
col = vs._get_or_create_collection('test_bottleneck')
print('collection ready:', col.name)
"
```

---

## Subtask 19.03: config.py — 惰性求值 + pydantic-settings 迁移

> **现状：** `Config` 类的所有属性是类级 `os.getenv()` 调用。`from config import Config` 触发所有 env 读取。且 `Config.LLM_API_KEY` 等值在部署后无法热更新。

**修改文件：** `config.py`

```python
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """pydantic-settings 管理的配置 — 支持 .env 和运行时重载。"""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    default_model: str = "glm-5.1"
    temperature: float = 0.7
    max_tokens: int = 1000

    # Database
    database_url: str = ""
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "emotional_chat"
    chroma_persist_directory: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Vector store
    vector_embedding_model: str = "all-MiniLM-L6-v2"
    vector_embedding_disabled: bool = False

    # Observability
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Cache
    redis_url: str = "redis://localhost:6379"
    cache_ttl: int = 3600

    # CORS
    cors_allow_all: bool = False
    frontend_origins: str = ""

    # Key governance
    llm_key_master_key: str = ""

    # Hermes
    hermes_tools_enabled: bool = False
    hermes_workspace_root: str = ""
    hermes_web_fetch_enabled: bool = False
    hermes_web_allowlist: str = ""
    hermes_shell_enabled: bool = False


@lru_cache()
def get_settings() -> Settings:
    """惰性创建 + 缓存 — 首次调用时才读取 env。"""
    return Settings()
```

**向后兼容层：** 现有代码的 `from config import Config; Config.LLM_API_KEY` 不变：

```python
# 文件末尾 — Config 保持为旧接口的兼容代理
class ConfigProxy:
    """Config 类保持旧接口，底层委托给 lazy settings。"""

    def __getattr__(self, name):
        s = get_settings()
        key = name.lower()
        # 兼容旧全大写命名
        for field in s.model_fields:
            if field.upper() == name:
                return getattr(s, field)
            if field == name.lower():
                return getattr(s, field)
        # 特殊兼容映射
        compat_map = {
            "OPENAI_API_KEY": "llm_api_key",
            "API_BASE_URL": "llm_base_url",
            "DASHSCOPE_API_KEY": "llm_api_key",
            "LANGCHAIN_TRACING_V2": None,
            "LANGCHAIN_API_KEY": None,
            "CHROMA_PERSIST_DIRECTORY": "chroma_persist_directory",
            "HERMES_TOOLS_ENABLED": "hermes_tools_enabled",
            "HERMES_WORKSPACE_ROOT": "hermes_workspace_root",
        }
        if name in compat_map:
            mapped = compat_map[name]
            if mapped is None:
                return None
            return getattr(s, mapped)
        raise AttributeError(f"Config has no attribute {name}")


Config = ConfigProxy()
```

**⚠️ Cursor 警告：**
- `pydantic-settings` 需要加到 `pyproject.toml` 依赖中：`uv add pydantic-settings`
- `ConfigProxy` 使用 `__getattr__` 而非直接继承 — 这样不用改现有所有 `from config import Config; Config.LLM_API_KEY` 的地方
- 但**有些地方直接 import 了 `Config.LLM_API_KEY` 作为模块级常量**（如 `from config import Config; KEY = Config.LLM_API_KEY`）— 这些需要改为函数调用
- `lru_cache()` 在热重载时不会自动清除 — 开发时可以 `get_settings.cache_clear()` 或在 lifespan 中重置
- LangChain 的 `LANGCHAIN_*` 变量是 env 级（被 LangChain SDK 直接读取），不需要经过 Config

**验证：**
```bash
# 1. 首次引用才读取 env
python -c "
from config import Config
import os
print('config imported — no env reads yet')
print('key:', Config.LLM_API_KEY[:5] if Config.LLM_API_KEY else '(empty)')
"

# 2. 热重载能力
python -c "
from config import get_settings
s1 = get_settings()
s2 = get_settings()
print('same instance:', s1 is s2)
# clear cache to force reload
get_settings.cache_clear()
s3 = get_settings()
print('new instance after clear:', s1 is not s3)
"
```

---

## Subtask 19.04: EnhancedContextAssembler — 并行化五步上下文组装

> **现状：** `assemble_context()` 的执行顺序是：识别重要轮次 → 短期记忆 → 长期记忆 → 用户画像 → 对话图谱。**没有一步依赖前一步的结果**，完全可并行。

**修改文件：** `backend/services/enhanced_context_assembler.py`

```python
async def assemble_context(self, ...) -> Dict[str, Any]:
    """并行化 5 个独立步骤。"""

    # 注意：_identify_important_turns 是纯计算，non-async
    important_markers = self._identify_important_turns(chat_history)

    # ── 并行执行 4 个独立 IO 操作 ─────────────────
    (
        short_term_context,
        long_term_memories,
        user_profile,
        conversation_graph,
    ) = await asyncio.gather(
        self._get_short_term(chat_history, important_markers),
        self._get_long_term(user_id, current_message),
        self._get_profile(user_id),
        self._get_graph(user_id),
    )

    # profile_summary 依赖 user_profile — 串行
    profile_summary = await self.profile_builder.generate_profile_summary(user_id)

    # ── 组装 ─────────────────────────────────────
    context = {
        "user_id": user_id,
        "session_id": session_id,
        "current_message": current_message,
        "current_emotion": {"emotion": emotion, "intensity": emotion_intensity},
        "short_term_memory": {
            "messages": short_term_context,
            "count": len(short_term_context) if short_term_context else 0,
            "important_turns": important_markers,
        },
        "long_term_memory": {
            "memories": long_term_memories,
            "count": len(long_term_memories) if long_term_memories else 0,
        },
        "user_profile": {"summary": profile_summary, "details": user_profile},
        "conversation_graph": conversation_graph,
        "timestamp": datetime.now().isoformat(),
    }
    return context


# ── 拆分为独立方法（每个都是 awaitable） ────────────────
async def _get_short_term(self, history, markers):
    return self.memory_manager.get_short_term_context(history, markers)

async def _get_long_term(self, user_id, query):
    return await self.memory_manager.retrieve_memories(
        user_id=user_id, query=query, n_results=5, days_limit=30, enable_decay=True
    )

async def _get_profile(self, user_id):
    return await self.profile_builder.build_profile(user_id)

async def _get_graph(self, user_id):
    return await self.profile_builder.build_conversation_graph(user_id)
```

**⚠️ Cursor 警告：**
- `_get_short_term` 内部调用 `get_short_term_context()` — 需要确认它是不是 sync 函数。如果是 sync，用 `asyncio.to_thread()` 包装
- `gather()` 至少需要 Python 3.8+，本项目的目标版本
- 如果某个子任务比其他的慢很多（如 long_term_memories 向量检索），整个 `gather` 会被那个慢任务拖住 — 这是预期行为

**验证：**
```bash
# bench: 对比串行 vs 并行的延迟
python -c "
import asyncio, time

async def bench():
    from backend.services.enhanced_context_assembler import EnhancedContextAssembler
    ca = EnhancedContextAssembler()

    # warmup
    for _ in range(3):
        await ca.assemble_context('test_user', 'test_session', '你好', [])

    start = time.time()
    for _ in range(10):
        await ca.assemble_context('test_user', 'test_session', '你好', [])
    elapsed = (time.time() - start) / 10
    print(f'平均请求耗时: {elapsed:.3f}s')

asyncio.run(bench())
"
```

---

## Subtask 19.05: MemoryService — 批量写入 + 异步化

> **现状：** `_sync_memories_to_db()` 在 `for memory in memories` 循环内逐条 `db.db.add()` 加一次 `db.db.commit()`。且使用同步 `with DatabaseManager()` 阻塞 event loop。

**修改文件：** `backend/services/memory_service.py`

```python
async def process_and_store_memories(self, ...) -> List[Dict[str, Any]]:
    memories = self.memory_manager.process_conversation(
        session_id=session_id,
        user_id=user_id,
        user_message=user_message,
        bot_response=bot_response,
        emotion=emotion,
        emotion_intensity=emotion_intensity,
    )

    if memories:
        synced_ids = await self._async_sync_memories_to_db(memories)
        # 不删除 chroma 条目 — 只标记为 unconfirmed
        for memory in memories:
            memory_id = memory.get("id")
            if memory_id and memory_id not in synced_ids:
                self.memory_manager.delete_memory(user_id, memory_id)
        memories = [m for m in memories if m.get("id") in synced_ids]

    return memories


async def _async_sync_memories_to_db(
    self, memories: List[Dict[str, Any]]
) -> set[str]:
    """异步批量写入 — 一次事务，一块提交。"""
    from backend.database import get_session

    synced_ids: set[str] = set()
    try:
        session = await asyncio.to_thread(get_session)
        new_items = []
        for memory in memories:
            mid = memory.get("id")
            if not mid:
                continue
            existing = session.query(MemoryItem).filter(
                MemoryItem.memory_id == mid
            ).first()
            if not existing:
                new_items.append(
                    MemoryItem(
                        memory_id=mid,
                        user_id=memory.get("user_id"),
                        session_id=memory.get("session_id"),
                        content=memory.get("content", ""),
                        summary=memory.get("summary", ""),
                        memory_type=memory.get("type", "other"),
                        emotion=memory.get("emotion"),
                        emotion_intensity=memory.get("intensity"),
                        importance=memory.get("importance", 0.5),
                        extraction_method=memory.get("extraction_method", "unknown"),
                        keywords=json.dumps(memory.get("keywords", []), ensure_ascii=False),
                    )
                )
            synced_ids.add(mid)

        # 批量 insert — 一次 commit
        if new_items:
            session.bulk_save_objects(new_items)
        session.commit()
    except Exception as e:
        logger.error("批量写入记忆失败: %s", e)
        session.rollback()
    finally:
        session.close()

    return synced_ids
```

**⚠️ Cursor 警告：**
- `sqlalchemy` 的 `bulk_save_objects()` 不触发 ORM 事件（如 `before_insert`）— 本项目中 MemoryItem 模型没有 ORM 事件，安全
- 如果在 MySQL 上运行，`bulk_save_objects` 性能提升约 10x-50x 对比逐条 add+commit
- `asyncio.to_thread()` 将 SQLAlchemy 同步调用放到线程池中，不阻塞 event loop

**验证：**
```bash
# bench: 写入 50 条记忆的延迟对比
python -c "
import asyncio, time, json

async def bench():
    from backend.services.memory_service import MemoryService
    ms = MemoryService()

    memories = [
        {'id': f'mem_{i}', 'user_id': 'test', 'session_id': 's1',
         'content': f'test memory {i}', 'type': 'other',
         'intensity': 5.0}
        for i in range(50)
    ]

    start = time.time()
    synced = await ms._async_sync_memories_to_db(memories)
    elapsed = time.time() - start
    print(f'批量写入 50 条: {elapsed:.3f}s, synced: {len(synced)}')

asyncio.run(bench())
"
```

---

## Subtask 19.06: PerformanceOptimizer — redis.asyncio 迁移

> **现状：** `PerformanceOptimizer.__init__` 使用 `redis.from_url()`（同步阻塞！），且 `_get_or_compute` 的缓存读取走 `ThreadPoolExecutor`，完全绕过了 asyncio 的优势。

**修改文件：** `backend/services/performance_optimizer.py`

```python
from redis.asyncio import Redis, from_url as async_redis_from_url


class AsyncPerformanceOptimizer:
    """使用 redis.asyncio 替换同步 Redis。"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._redis: Redis | None = None  # lazy init
        self._lock = asyncio.Lock()

    async def _ensure_redis(self):
        if self._redis is None:
            async with self._lock:
                if self._redis is None:  # double-check
                    self._redis = await async_redis_from_url(
                        self._redis_url,
                        decode_responses=True,
                        max_connections=50,  # 连接池
                    )
        return self._redis

    async def get(self, key: str) -> str | None:
        r = await self._ensure_redis()
        try:
            return await r.get(key)
        except (ConnectionError, TimeoutError) as e:
            logger.warning("Redis 不可用（降级为 cache miss）: %s", e)
            return None

    async def set(self, key: str, value: str, ttl: int = 3600):
        r = await self._ensure_redis()
        try:
            await r.set(key, value, ex=ttl)
        except (ConnectionError, TimeoutError) as e:
            logger.warning("Redis 写入失败（降级）: %s", e)

    async def parallel_processing(self, user_input, emotion_analyzer,
                                  safety_checker, memory_retriever):
        start = time.time()

        # 并行获取缓存命中情况
        cache_keys = {
            "emotion": f"emotion:{hashlib.md5(user_input.encode()).hexdigest()}",
            "safety": f"safety:{hashlib.md5(user_input.encode()).hexdigest()}",
            "memory": f"memory:{hashlib.md5(user_input.encode()).hexdigest()}",
        }

        # 并行查缓存 + 并行计算
        async def get_or_compute(cache_key, coro_fn):
            cached = await self.get(cache_key)
            if cached is not None:
                return json.loads(cached)
            result = await coro_fn()  # 直接 await async 函数
            await self.set(cache_key, json.dumps(result))
            return result

        emotion_task = get_or_compute(
            cache_keys["emotion"],
            lambda: emotion_analyzer.analyze(user_input),
        )
        safety_task = get_or_compute(
            cache_keys["safety"],
            lambda: safety_checker.check(user_input),
        )
        memory_task = get_or_compute(
            cache_keys["memory"],
            lambda: memory_retriever.retrieve(user_input),
        )

        emotion_result, safety_result, memory_result = await asyncio.gather(
            emotion_task, safety_task, memory_task
        )

        return {
            "emotion": emotion_result,
            "safety": safety_result,
            "memory": memory_result,
            "processing_time": time.time() - start,
            "parallel_optimization": True,
        }


# ── 保持旧接口兼容 ─────────────────────────────────────
performance_optimizer = AsyncPerformanceOptimizer()
```

**⚠️ Cursor 警告：**
- `redis.asyncio` 是 `redis-py` 4.x+ 的内置模块 — 确认 `pyproject.toml` 中 `redis>=4.5.0`
- 现有的 `ThreadPoolExecutor` 用户（`stream_handler`, `cache_manager` 等模块级单例）需要同步迁移
- 如果 Redis 不可用，get/set 降级为 cache miss，不抛异常

**验证：**
```bash
python -c "
import asyncio

async def bench():
    from backend.services.performance_optimizer import performance_optimizer as po
    r = await po._ensure_redis()
    await po.set('test_bottleneck', 'hello', ttl=10)
    val = await po.get('test_bottleneck')
    print('redis async OK:', val)
    await r.delete('test_bottleneck')

asyncio.run(bench())
"
```

---

## Subtask 19.07: 服务层惰性初始化 — 消除上帝对象

> **现状：** `ChatService.__init__`, `EnhancedChatService.__init__`, `OptimizedChatService.__init__` 创建时即初始化 MemoryService、ContextService、EnhancedInputProcessor、RAG、Intent 等所有组件。**90% 的请求只用到 LLM 响应，不需要全部组件**。

**修改所有服务类：**

1. 所有 `self.xxx = XxxService()` 改为 `@cached_property` 惰性求值
2. 将慢初始化（ChromaDB、RAG）移到 `async def lazy_init()` 方法

```python
from functools import cached_property


class EnhancedChatService:
    """惰性初始化的服务类。"""

    def __init__(self, use_rag: bool = True, use_intent: bool = True, ...):
        # 只保存配置，不做任何 IO
        self._cfg = {
            "use_rag": use_rag,
            "use_intent": use_intent,
            "use_enhanced_processor": use_enhanced_processor,
            "enable_proactive_recall": enable_proactive_recall,
        }

    @cached_property
    def memory_manager(self):
        return EnhancedMemoryManager()

    @cached_property
    def profile_builder(self):
        return UserProfileBuilder()

    @cached_property
    def context_assembler(self):
        return EnhancedContextAssembler()

    @cached_property
    def proactive_recall(self):
        if self._cfg.get("enable_proactive_recall"):
            return ProactiveRecallSystem()
        return None

    @cached_property
    def rag_service(self):
        if not self._cfg.get("use_rag"):
            return None
        try:
            from backend.modules.rag.services.rag_service import RAGIntegrationService
            return RAGIntegrationService()
        except ImportError:
            return None

    @cached_property
    def intent_service(self):
        if not self._cfg.get("use_intent"):
            return None
        try:
            from backend.modules.intent.services import IntentService
            return IntentService()
        except ImportError:
            return None
```

同样的模式应用到 `ChatService` 和 `OptimizedChatService`。

**⚠️ Cursor 警告：**
- `@cached_property` 是描述符 — 在类上使用，不能在 `__init__` 中赋值同名属性。构造时 `self.xxx = ...` 会覆盖 `cached_property`
- 需要检查当前代码中是否在 `__init__` 之后又在方法中重新赋值了这些属性
- 惰性初始化的优点是请求只在需要时才创建组件，但缺点是在高并发下第一次访问可能有多线程竞争 — `cached_property` 在 Python 3.12+ 有线程安全保证，早期版本用 `@property` + 手动 `_xxx` 缓存

**验证：**
```bash
python -c "
from backend.services.enhanced_chat_service import EnhancedChatService
import time

start = time.time()
svc = EnhancedChatService(use_rag=False, use_intent=False, enable_proactive_recall=False)
create_time = time.time() - start
print(f'创建服务（无 IO）: {create_time:.3f}s')

# 首次访问触发实际初始化
start = time.time()
_ = svc.context_assembler
first_use = time.time() - start
print(f'首次使用 context_assembler: {first_use:.3f}s')
"
```

---

## Subtask 19.08: app.py — 消除模块级 import swamp

> **现状：** `app.py` 模块作用域有 7 个 `try/except ImportError` 块，每个都尝试 import 一个 router。import 链级联触发所有服务的初始化。而且这些在 `python -c "from backend.app import create_app"` 时全部执行。

**修改文件：** `backend/app.py`

```python
def create_app() -> FastAPI:
    app = FastAPI(
        title="ContextGate API",
        description="The Intelligent Gateway for LLM Context Management",
        version="4.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    _setup_cors(app)

    # 路由：使用 lazy_include 模式
    _lazy_include(app, "backend.routers.chat", "chat_router")
    _lazy_include(app, "backend.routers.memory", "memory_router")
    _lazy_include(app, "backend.routers.feedback", "feedback_router")
    _lazy_include(app, "backend.routers.evaluation", "evaluation_router")
    _lazy_include(app, "backend.routers.emotion_analysis", "emotion_router")
    _lazy_include(app, "backend.routers.personalization", "personalization_router")
    _lazy_include(app, "backend.modules.rag.routers.rag_router", "rag_router")
    _lazy_include(app, "backend.routers.enhanced_chat", "enhanced_chat_router")
    _lazy_include(app, "backend.routers.agent", "agent_router")
    _lazy_include(app, "backend.routers.hermes", "hermes_router")
    _lazy_include(app, "backend.routers.performance", "performance_router")
    _lazy_include(app, "backend.routers.streaming_chat", "streaming_router")
    _lazy_include(app, "backend.modules.intent.routers", "intent_router")

    # 静态文件
    _setup_static_files(app)

    # 根路由
    @app.get("/")
    async def root():
        return {
            "name": "ContextGate",
            "version": "4.0.0",
            "status": "running",
        }

    return app


def _lazy_include(app: FastAPI, module_path: str, attr: str):
    """惰性 import — 只在 create_app() 调用时执行，不污染模块作用域。"""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        router = getattr(mod, attr, None)
        if router:
            app.include_router(router)
    except ImportError:
        pass  # 可选模块静默跳过
```

**安全修复 — StaticFiles 需要 auth：**

```python
def _setup_static_files(app: FastAPI):
    """/uploads 挂载 auth 中间件（不绕过 API key 验证）。"""
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from pathlib import Path

    upload_dir = Path(__file__).resolve().parent.parent / "uploads"
    upload_dir.mkdir(exist_ok=True)

    # 使用 ASGI app 包装，在静态文件前加一道 auth 检查
    class AuthStaticFiles(StaticFiles):
        async def __call__(self, scope, receive, send):
            headers = dict(scope.get("headers", []))
            # 检查 X-API-Key（简单验证，完整验证委托给 verify_api_key）
            api_key = dict(headers).get(b"x-api-key", b"").decode()
            if not api_key:
                await JSONResponse(
                    status_code=401,
                    content={"code": "AUTH_001", "message": "missing_api_key"},
                )(scope, receive, send)
                return
            await super().__call__(scope, receive, send)

    app.mount("/uploads", AuthStaticFiles(directory=str(upload_dir)), name="uploads")
```

**⚠️ Cursor 警告：**
- `_lazy_include` 会 catch 所有 `ImportError` — 如果某个必选模块 import 失败，它被静默跳过，不会在启动时报错。对于必选模块（如 `chat_router`），需加上日志
- 所有 router 的 `from ... import ...` 原来在模块级执行，现在推迟到 `create_app()` 执行时 — 不影响功能
- `AuthStaticFiles` 是轻量版本 — 生产环境应使用完整 `verify_api_key` Depends

**验证：**
```bash
# 1. 启动不应 import 任何可选模块
python -c "
from backend.app import create_app
app = create_app()
print('routes:', len(app.routes))
"

# 2. /uploads 需要 auth
curl -s http://localhost:8000/uploads/test.txt
# → 401 {\"code\": \"AUTH_001\"}
```

---

## Subtask 19.09: 汇集 — lifespan 预热 + 初始化顺序

> **现状：** 没有任何预热机制。第一个请求触发了 ChromaDB、Embedding、数据库连接等所有慢操作的冷启动。

**修改文件：** `backend/app.py` — 增加 FastAPI lifespan

```python
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 — 启动时预热，关闭时清理。"""
    logger.info("═" * 40)
    logger.info("ContextGate 启动中...")
    logger.info("═" * 40)

    # Phase 1: 数据库初始化
    from backend.database import init_database
    init_database()
    logger.info("✓ 数据库连接池就绪")

    # Phase 2: VectorStore 预热（惰性但触发缓存的 ONNX 下载）
    from backend.vector_store import VectorStore
    vs = VectorStore()
    # 预热集合，ONNX 模型此时下载（如果有网络且不禁用）
    try:
        col = vs._get_or_create_collection("conversations")
        col.count()  # 轻量调用来确保 embedding 函数已加载
        logger.info("✓ 向量存储就绪")
    except Exception as e:
        logger.warning("向量存储预热失败（不影响核心功能）: %s", e)

    # Phase 3: KeyManager 校验
    try:
        from backend.core.key_manager import KeyManager
        KeyManager()  # 验证 LLM_KEY_MASTER_KEY 是否正确
        logger.info("✓ KeyManager 就绪")
    except RuntimeError as e:
        logger.warning("KeyManager 未就绪: %s", e)

    # Phase 4: Redis 连接预热
    try:
        from backend.services.performance_optimizer import performance_optimizer
        r = await performance_optimizer._ensure_redis()
        await r.ping()
        logger.info("✓ Redis 连接池就绪")
    except Exception as e:
        logger.info("Redis 不可用（缓存降级为 memory）: %s", e)

    logger.info("═" * 40)
    logger.info("ContextGate 就绪")
    logger.info("═" * 40)

    yield  # 应用运行

    # 关闭时清理
    logger.info("ContextGate 关闭中...")
    # 关闭 Redis 连接池
    try:
        from backend.services.performance_optimizer import performance_optimizer
        if performance_optimizer._redis:
            await performance_optimizer._redis.close()
    except Exception:
        pass
    logger.info("ContextGate 已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ContextGate API",
        lifespan=lifespan,  # ← 注册 lifespan
        ...
    )
```

**验证：**
```bash
# 启动日志应有预热阶段的每个 ✓
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --log-level info 2>&1 | head -20
# → 应看到:
#   ════════════════════════════════════════
#   ContextGate 启动中...
#   ════════════════════════════════════════
#   ✓ 数据库连接池就绪
#   ✓ 向量存储就绪
#   ✓ KeyManager 就绪
#   ✓ Redis 连接池就绪
#   ════════════════════════════════════════
#   ContextGate 就绪
#   ════════════════════════════════════════
```

---

## Subtask 19.10: 整合测试 — benchmark 对比

> 所有 subtask 完成后，跑一份综合 benchmark，收集改造前后的对比数据。

**文件:** `benchmarks/test_bottleneck_before_after.py`

```python
"""
基准测试 — 对比改造前后的延迟指标。

用法:
  # 改造前测一次
  git stash && python benchmarks/test_bottleneck_before_after.py > before.txt
  # 改造后测一次
  git stash pop && python benchmarks/test_bottleneck_before_after.py > after.txt
  # 对比
  diff -u before.txt after.txt
"""

import asyncio
import time
import sys


async def bench_startup_time():
    """测从 import create_app 到 lifespan 结束的耗时"""
    start = time.time()
    from backend.app import create_app
    app = create_app()
    elapsed = time.time() - start
    print(f"create_app(): {elapsed:.3f}s")
    return elapsed


async def bench_first_request():
    """测第一个 chat 请求的冷启动耗时"""
    start = time.time()
    from backend.services.chat_service import ChatService
    svc = ChatService()
    elapsed = time.time() - start
    print(f"ChatService() init: {elapsed:.3f}s")
    return elapsed


async def bench_memory_write(count=50):
    """测批量写入 count 条记忆的耗时"""
    from backend.services.memory_service import MemoryService
    ms = MemoryService()
    memories = [
        {"id": f"bench_{i}", "user_id": "bench", "session_id": "bench_s",
         "content": f"benchmark test {i}", "type": "other", "intensity": 5.0}
        for i in range(count)
    ]
    start = time.time()
    synced = await ms._sync_memories_to_db(memories)
    elapsed = time.time() - start
    print(f"sync {count} memories: {elapsed:.3f}s ({count/max(elapsed, 0.001):.0f}条/s)")
    return elapsed


async def main():
    print("═" * 50)
    print(f"ContextGate 性能基准测试 ({sys.argv[1] if len(sys.argv) > 1 else 'current'})")
    print("═" * 50)
    await bench_startup_time()
    await bench_first_request()
    await bench_memory_write(50)
    await bench_memory_write(200)
    print("═" * 50)


asyncio.run(main())
```

**验证：**
```bash
python benchmarks/test_bottleneck_before_after.py before
# → 记录改造前的每个指标

python benchmarks/test_bottleneck_before_after.py after
# → 记录改造后的每个指标，应观察到：
#   create_app():  <0.5s  (vs 原 3-10s+)
#   ChatService() init: <0.01s  (vs 原 0.5-3s)
#   sync 50 memories: <0.1s  (vs 原 1-5s)
```

---

## 执行顺序

```
19.01 (database.py) ─→ 19.03 (config.py)
       │                    │
       ├──── 19.02 (vector_store.py) ←────────┐
       │                            │         │
       └──── 19.04 (context assembly) ── 19.07 (lazy init)
                            │                    │
                     19.05 (memory batch) ←──────┘
                     19.06 (async redis)
                            │
                     19.08 (app.py import swamp)
                            │
                     19.09 (lifespan + warmup)
                            │
                     19.10 (benchmark + compare)
```

- 19.01 → 19.03: 数据库和配置是全局基础，先改
- 19.02: 向量存储独立，可与其他并行
- 19.04 → 19.05: 上下文和记忆是请求路径核心
- 19.06: Redis 独立改造
- 19.07: 依赖上面多个改完后的惰性构造
- 19.08: app 入口，最后整合
- 19.09: 预热 + 生命周期
- 19.10: 最后验证

每个 subtask 一个 commit，提交信息格式：`chore(bottleneck): 19.N - subtask name`
