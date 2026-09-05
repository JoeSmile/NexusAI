"""Shared Redis helpers — lazy connect + silent degrade (Task 35 / 32.64).

契约: redis 不可用时返回 None / 跳过，调用方不得因缓存抛 500。
失败后 RETRY_AFTER_SEC 秒允许重试（Task 36），避免永久降级。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

RETRY_AFTER_SEC = 30.0

_sync_clients: dict[tuple[bool, str | int | None], Any] = {}
_sync_failed: dict[tuple[bool, str | int | None], float] = {}  # slot -> monotonic 失败时间戳
_async_clients: dict[bool, Any] = {}
_async_failed: dict[bool, float] = {}
_async_lock: asyncio.Lock | None = None


def _assemble_redis_url(
    host: str,
    port: str | int = 6379,
    password: str | None = None,
    db: str | int = 0,
) -> str:
    """Build ``redis://[:password@]host:port/db`` from discrete parts."""
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


def resolve_redis_url(default: str = "redis://localhost:6379") -> str:
    """Resolve Redis URL from env / compose / Config (Task 41 P0-8 / E_3 chore).

    Priority:
    1. ``REDIS_URL`` env (explicit full URL)
    2. ``REDIS_HOST`` + ``REDIS_PORT`` (+ optional password/db) — docker-compose path
    3. root ``config.Config.REDIS_URL`` (pydantic Settings proxy)
    4. ``default`` (localhost)
    """
    env_url = (os.getenv("REDIS_URL") or "").strip()
    if env_url:
        return env_url

    host = (os.getenv("REDIS_HOST") or "").strip()
    if host:
        port = (os.getenv("REDIS_PORT") or "6379").strip() or "6379"
        password = (os.getenv("REDIS_PASSWORD") or "").strip() or None
        db = (os.getenv("REDIS_DB") or "0").strip() or "0"
        return _assemble_redis_url(host, port, password, db)

    try:
        from config import Config

        cfg_url = getattr(Config, "REDIS_URL", None)
        if cfg_url and str(cfg_url).strip():
            return str(cfg_url).strip()
    except Exception:
        pass

    return default


def resolve_ratelimit_redis_url() -> str:
    """限流/并发槽 Redis：``REDIS_RATELIMIT_URL`` 优先，未设则回退 ``REDIS_URL``。

    禁止指向 langfuse-redis。记忆队列保持 db1，不走本函数。
    """
    extra = (os.getenv("REDIS_RATELIMIT_URL") or "").strip()
    if extra:
        return extra
    return resolve_redis_url()


SyncSlot = tuple[bool, str | int | None]


def _should_retry(failed: dict[Any, float], slot: Any) -> bool:
    ts = failed.get(slot)
    return ts is None or (time.monotonic() - ts) > RETRY_AFTER_SEC


def get_sync_redis(*, decode_responses: bool = False, db: str | int | None = None) -> Any | None:
    """惰性同步客户端；按 (decode_responses, db) 分槽；失败后 TTL 内不再重试。

    I-5(评审 08-15)：``db`` 显式指定时覆盖 REDIS_DB（队列用独立 db，与缓存/限流隔离）。
    ``socket_timeout=0.5`` 防止 Redis 半死时 EVAL/GET 无限阻塞、降级永不触发。
    """
    slot = (decode_responses, db)
    if not _should_retry(_sync_failed, slot):
        return None
    if slot in _sync_clients:
        return _sync_clients[slot]
    try:
        import redis

        url = resolve_redis_url()
        if db is not None:
            url = url.rsplit("/", 1)[0] + f"/{db}"
        client = redis.Redis.from_url(
            url,
            decode_responses=decode_responses,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        client.ping()
        _sync_clients[slot] = client
        _sync_failed.pop(slot, None)
        return client
    except Exception as e:
        logger.warning("Redis sync 不可用(降级): %s", e)
        _sync_failed[slot] = time.monotonic()
        return None


_rl_clients: dict[tuple[bool, str], Any] = {}
_rl_failed: dict[tuple[bool, str], float] = {}


def get_ratelimit_sync_redis(*, decode_responses: bool = True) -> Any | None:
    """并发槽 / 限流热路径客户端。

    未设 ``REDIS_RATELIMIT_URL`` 时复用 ``get_sync_redis``（同一实例 db0）。
    独立 URL 时 ``socket_timeout`` 150ms，超时不在本函数内重试。
    """
    extra = (os.getenv("REDIS_RATELIMIT_URL") or "").strip()
    if not extra:
        return get_sync_redis(decode_responses=decode_responses)
    slot = (decode_responses, extra)
    if not _should_retry(_rl_failed, slot):
        return None
    if slot in _rl_clients:
        return _rl_clients[slot]
    try:
        import redis

        client = redis.Redis.from_url(
            extra,
            decode_responses=decode_responses,
            socket_connect_timeout=0.15,
            socket_timeout=0.15,
        )
        client.ping()
        _rl_clients[slot] = client
        _rl_failed.pop(slot, None)
        return client
    except Exception as e:
        logger.warning("Redis ratelimit 不可用(降级): %s", e)
        _rl_failed[slot] = time.monotonic()
        return None


def _async_lock_get() -> asyncio.Lock:
    global _async_lock
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    return _async_lock


async def get_async_redis(*, decode_responses: bool = True) -> Any | None:
    """惰性 async 客户端；按 decode_responses 分槽；失败后 TTL 内返回 None。"""
    if not _should_retry(_async_failed, decode_responses):
        return None
    if decode_responses in _async_clients:
        return _async_clients[decode_responses]
    async with _async_lock_get():
        if not _should_retry(_async_failed, decode_responses):
            return None
        if decode_responses in _async_clients:
            return _async_clients[decode_responses]
        try:
            from redis.asyncio import from_url as async_redis_from_url

            client = async_redis_from_url(
                resolve_redis_url(),
                decode_responses=decode_responses,
                max_connections=50,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            await client.ping()
            _async_clients[decode_responses] = client
            _async_failed.pop(decode_responses, None)
            return client
        except Exception as e:
            logger.warning("Redis async 不可用(降级): %s", e)
            _async_failed[decode_responses] = time.monotonic()
            return None


async def close_async_redis() -> None:
    """关闭共享 async 客户端并清失败标志（app lifespan shutdown）。"""
    for client in list(_async_clients.values()):
        try:
            await client.aclose()
        except Exception:
            pass
    _async_clients.clear()
    _async_failed.clear()


def close_sync_redis() -> None:
    """关闭共享同步客户端并清失败标志（热更新/测试用；进程退出可不调）。"""
    for client in list(_sync_clients.values()):
        try:
            client.close()
        except Exception:
            pass
    _sync_clients.clear()
    _sync_failed.clear()
    for client in list(_rl_clients.values()):
        try:
            client.close()
        except Exception:
            pass
    _rl_clients.clear()
    _rl_failed.clear()


def reset_redis_clients_for_tests() -> None:
    """测试用：重置惰性连接与失败标志。"""
    global _async_lock
    close_sync_redis()
    _async_clients.clear()
    _async_failed.clear()
    _async_lock = None


def cache_key(domain: str, name: str, tenant: str, key: str) -> str:
    """统一前缀: ``<域>:<名>:<租户>:<键>``（如 ``rag:l1:t1:abc``）。"""
    return f"{domain}:{name}:{tenant or 'default'}:{key}"


# 域前缀约定（详表见 docs/CACHE.md）
CACHE_KEY_DOMAINS: dict[str, str] = {
    "rag": "RAG 答案/向量 (rag:a / rag:e / rag:epoch / rag:lock)",
    "chat": "对话与 PerformanceOptimizer (chat:v / chat:epoch / chat:lock)",
    "ctx": "能力/上下文缓存 (预留)",
    "rl": "限流桶 (rl:cap / rl:rag / …)",
    "mem": "记忆热缓存 (mem:warm / mem:cold TTL 300s；hot 不缓存)",
    "llm": "LLM 并发 in-flight (llm:in-flight:global / llm:in-flight:{hash})",
    "belief": "意图漏斗当前任务 (belief:cur:{tid}:{uid}:{session})",
    "search": "热点付费搜索次数帽 (search:cap:global:{month} / search:cap:{tid}:{day|month})",
    "img": "会话图片描述缓存 (img:desc:{tid}:{sha256[:16]}，旧 attachment_id key 只读兼容)",
}


async def async_acquire_lock(
    redis: Any | None, lock_key: str, *, ttl: int = 10
) -> bool:
    """单飞锁 SET NX EX；无 redis 时当作已拿到锁（直接回源）。"""
    if redis is None:
        return True
    try:
        return bool(await redis.set(lock_key, "1", nx=True, ex=ttl))
    except Exception:
        return True


async def async_release_lock(redis: Any | None, lock_key: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(lock_key)
    except Exception:
        pass
