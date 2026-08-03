"""Shared Redis helpers — lazy connect + silent degrade (Task 35 / 32.64).

契约: redis 不可用时返回 None / 跳过，调用方不得因缓存抛 500。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_sync_clients: dict[bool, Any] = {}
_sync_failed: dict[bool, bool] = {}
_async_clients: dict[bool, Any] = {}
_async_failed: dict[bool, bool] = {}
_async_lock: asyncio.Lock | None = None


def resolve_redis_url(default: str = "redis://localhost:6379") -> str:
    url = (os.getenv("REDIS_URL") or "").strip() or default
    try:
        from config import Config

        cfg = getattr(Config, "REDIS_URL", None)
        if cfg:
            url = str(cfg)
    except Exception:
        pass
    return url


def get_sync_redis(*, decode_responses: bool = False) -> Any | None:
    """惰性同步客户端；按 decode_responses 分槽；失败后本槽不再重试（直至 reset）。"""
    if _sync_failed.get(decode_responses):
        return None
    if decode_responses in _sync_clients:
        return _sync_clients[decode_responses]
    try:
        import redis

        client = redis.Redis.from_url(
            resolve_redis_url(),
            decode_responses=decode_responses,
            socket_connect_timeout=0.5,
        )
        client.ping()
        _sync_clients[decode_responses] = client
        return client
    except Exception as e:
        logger.warning("Redis sync 不可用(降级): %s", e)
        _sync_failed[decode_responses] = True
        return None


def _async_lock_get() -> asyncio.Lock:
    global _async_lock
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    return _async_lock


async def get_async_redis(*, decode_responses: bool = True) -> Any | None:
    """惰性 async 客户端；按 decode_responses 分槽；失败返回 None。"""
    if _async_failed.get(decode_responses):
        return None
    if decode_responses in _async_clients:
        return _async_clients[decode_responses]
    async with _async_lock_get():
        if _async_failed.get(decode_responses):
            return None
        if decode_responses in _async_clients:
            return _async_clients[decode_responses]
        try:
            from redis.asyncio import from_url as async_redis_from_url

            client = async_redis_from_url(
                resolve_redis_url(),
                decode_responses=decode_responses,
                max_connections=50,
            )
            await client.ping()
            _async_clients[decode_responses] = client
            return client
        except Exception as e:
            logger.warning("Redis async 不可用(降级): %s", e)
            _async_failed[decode_responses] = True
            return None


async def close_async_redis() -> None:
    for client in list(_async_clients.values()):
        try:
            await client.aclose()
        except Exception:
            pass
    _async_clients.clear()


def reset_redis_clients_for_tests() -> None:
    """测试用：重置惰性连接与失败标志。"""
    global _async_lock
    _sync_clients.clear()
    _sync_failed.clear()
    _async_clients.clear()
    _async_failed.clear()
    _async_lock = None


def cache_key(domain: str, name: str, tenant: str, key: str) -> str:
    """统一前缀: ``<域>:<名>:<租户>:<键>``（如 ``rag:l1:t1:hash``）。"""
    return f"{domain}:{name}:{tenant}:{key}"
