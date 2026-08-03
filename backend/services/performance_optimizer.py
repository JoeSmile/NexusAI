#!/usr/bin/env python3
"""
性能优化服务 — redis.asyncio 惰性连接（Task 19.06）
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncGenerator, Callable
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any

from backend.logging_config import get_logger

logger = get_logger(__name__)


class PerformanceOptimizer:
    """使用 redis.asyncio 的性能优化器（惰性连接，失败降级；Task 35 经 redis_tools）。"""

    def __init__(self, redis_url: str | None = None):
        from backend.core.redis_tools import resolve_redis_url

        self._redis_url = redis_url or resolve_redis_url()
        self._redis = None
        self.thread_pool = ThreadPoolExecutor(max_workers=10)
        self.cache_ttl = 3600

    async def _ensure_redis(self):
        if self._redis is not None:
            return self._redis
        from backend.core.redis_tools import get_async_redis

        # 共享进程级 async 客户端；URL 已由 redis_tools 解析
        self._redis = await get_async_redis(decode_responses=True)
        return self._redis

    async def close(self) -> None:
        # 共享客户端由 redis_tools 管理；实例侧仅清引用
        self._redis = None

    async def get(self, key: str) -> str | None:
        r = await self._ensure_redis()
        if r is None:
            return None
        try:
            return await r.get(key)
        except Exception as e:
            logger.warning("Redis 不可用（降级为 cache miss）: %s", e)
            return None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        r = await self._ensure_redis()
        if r is None:
            return
        try:
            await r.set(key, value, ex=ttl or self.cache_ttl)
        except Exception as e:
            logger.warning("Redis 写入失败（降级）: %s", e)

    async def delete(self, *keys: str) -> None:
        r = await self._ensure_redis()
        if r is None or not keys:
            return
        try:
            await r.delete(*keys)
        except Exception as e:
            logger.warning("Redis delete 失败: %s", e)

    async def ping(self) -> bool:
        r = await self._ensure_redis()
        if r is None:
            return False
        try:
            return bool(await r.ping())
        except Exception:
            return False

    def cache_key(self, prefix: str, content: str, tenant_id: str = "default") -> str:
        """逻辑键（不含 epoch）；CacheManager 写入 ``chat:v:<ep>:<tenant>:<逻辑键>``。"""
        content_hash = hashlib.md5(content.encode()).hexdigest()
        return f"{prefix}:{tenant_id or 'default'}:{content_hash}"

    async def parallel_processing(
        self,
        user_input: str,
        safety_checker,
        memory_retriever,
    ) -> dict[str, Any]:
        start_time = time.time()
        loop = asyncio.get_running_loop()
        cm = CacheManager(self)

        async def get_or_compute(logical_key: str, sync_fn: Callable[[], Any]):
            async def compute():
                return await loop.run_in_executor(self.thread_pool, sync_fn)

            return await cm.get_or_set(logical_key, compute)

        safety_result, memory_result = await asyncio.gather(
            get_or_compute(
                self.cache_key("safety", user_input),
                lambda: safety_checker.check(user_input),
            ),
            get_or_compute(
                self.cache_key("memory", user_input),
                lambda: memory_retriever.retrieve(user_input),
            ),
        )

        return {
            "safety": safety_result,
            "memory": memory_result,
            "processing_time": time.time() - start_time,
            "parallel_optimization": True,
        }

    async def _get_or_compute(self, cache_key: str, compute_func) -> Any:
        try:
            cached = await self.get(cache_key)
            if cached:
                return json.loads(cached)
            result = await compute_func()
            await self.set(cache_key, json.dumps(result))
            return result
        except Exception as e:
            logger.error(f"缓存操作失败: {e}")
            return await compute_func()

    async def stream_response(self, prompt: str, llm_client) -> AsyncGenerator[str, None]:
        try:
            async for chunk in llm_client.stream(prompt):
                if chunk:
                    yield f"data: {chunk}\n\n"
                    await asyncio.sleep(0.01)
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"流式响应失败: {e}")
            yield f"data: 抱歉，生成过程中出现错误: {e!s}\n\n"

    def fallback_strategy(self, error_type: str, user_input: str) -> str:
        fallback_responses = {
            "llm_timeout": "抱歉，我现在有点忙，请稍后再试。",
            "memory_timeout": "让我用最近的信息来帮助你。",
            "vector_error": "我会记住你的话，稍后给你更好的回复。",
            "general_error": "我遇到了一些技术问题，但我会尽力帮助你。",
        }
        return fallback_responses.get(error_type, fallback_responses["general_error"])

    async def async_task_queue(self, task_func, *args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.thread_pool, task_func, *args, **kwargs)
        except Exception as e:
            logger.error(f"异步任务执行失败: {e}")

    def performance_monitor(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(f"函数 {func.__name__} 执行时间: {execution_time:.3f}s")
                if execution_time > 3.0:
                    logger.warning(
                        f"函数 {func.__name__} 执行时间过长: {execution_time:.3f}s"
                    )
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(
                    f"函数 {func.__name__} 执行失败，耗时: {execution_time:.3f}s, 错误: {e}"
                )
                raise

        return wrapper

    async def get_performance_metrics(self) -> dict[str, Any]:
        try:
            r = await self._ensure_redis()
            if r is None:
                return {"redis": "unavailable", "cache_ttl": self.cache_ttl}
            redis_info = await r.info()
            return {
                "redis_connected_clients": redis_info.get("connected_clients", 0),
                "redis_used_memory": redis_info.get("used_memory_human", "0B"),
                "redis_hit_rate": await self._calculate_hit_rate(),
                "thread_pool_active": self.thread_pool._threads,
                "cache_ttl": self.cache_ttl,
            }
        except Exception as e:
            logger.error(f"获取性能指标失败: {e}")
            return {"error": str(e)}

    async def _calculate_hit_rate(self) -> float:
        try:
            r = await self._ensure_redis()
            if r is None:
                return 0.0
            info = await r.info()
            hits = info.get("keyspace_hits", 0)
            misses = info.get("keyspace_misses", 0)
            total = hits + misses
            return (hits / total * 100) if total > 0 else 0.0
        except Exception:
            return 0.0

    # 兼容旧代码访问 .redis_client 的属性名（返回 self，暴露 async get/set/ping）
    @property
    def redis_client(self):
        return self


class StreamingResponseHandler:
    def __init__(self):
        self.active_streams = {}

    async def create_stream(self, stream_id: str, generator_func):
        self.active_streams[stream_id] = {
            "created_at": time.time(),
            "status": "active",
        }
        try:
            async for chunk in generator_func():
                yield chunk
        finally:
            self.active_streams.pop(stream_id, None)

    def get_active_streams(self) -> dict[str, Any]:
        current_time = time.time()
        active_streams = {}
        for stream_id, info in list(self.active_streams.items()):
            if current_time - info["created_at"] < 300:
                active_streams[stream_id] = info
            else:
                self.active_streams.pop(stream_id, None)
        return active_streams


class CacheManager:
    """异步缓存管理器 — 单飞锁 + epoch 失效 + 滑动 TTL（Task 35.04 / RAG 模板）。"""

    def __init__(self, optimizer: PerformanceOptimizer):
        self._opt = optimizer
        self.default_ttl = 3600
        self._lock_ttl = 10
        self._wait_timeout_s = 0.5

    def _epoch_redis_key(self, tenant_id: str) -> str:
        return f"chat:epoch:{tenant_id or 'default'}"

    def _value_key(self, logical_key: str, tenant_id: str, epoch: int) -> str:
        return f"chat:v:{epoch}:{tenant_id or 'default'}:{logical_key}"

    def _lock_key(self, value_key: str) -> str:
        digest = hashlib.md5(value_key.encode()).hexdigest()[:16]
        return f"chat:lock:{digest}"

    async def get_epoch(self, tenant_id: str = "default") -> int:
        r = await self._opt._ensure_redis()
        if r is None:
            return 0
        try:
            v = await r.get(self._epoch_redis_key(tenant_id))
            return int(v) if v else 0
        except Exception:
            return 0

    async def bump_epoch(self, tenant_id: str = "default") -> int:
        """写路径批量失效：INCR epoch，旧 chat:v:* 键不再被读取。"""
        r = await self._opt._ensure_redis()
        if r is None:
            return 0
        try:
            return int(await r.incr(self._epoch_redis_key(tenant_id)))
        except Exception as e:
            logger.warning("chat epoch bump 失败(降级): %s", e)
            return 0

    async def get_or_set(
        self,
        key: str,
        compute_func,
        ttl: int | None = None,
        *,
        tenant_id: str = "default",
    ) -> Any:
        from backend.core.redis_tools import async_acquire_lock, async_release_lock

        ttl = ttl or self.default_ttl
        tid = tenant_id or "default"
        epoch = await self.get_epoch(tid)
        full_key = self._value_key(key, tid, epoch)

        cached = await self._get_json(full_key, ttl=ttl)
        if cached is not None:
            return cached

        r = await self._opt._ensure_redis()
        lock_key = self._lock_key(full_key)
        got_lock = await async_acquire_lock(r, lock_key, ttl=self._lock_ttl)
        if got_lock:
            try:
                cached = await self._get_json(full_key, ttl=ttl)
                if cached is not None:
                    return cached
                result = await compute_func()
                await self._opt.set(full_key, json.dumps(result), ttl=ttl)
                return result
            finally:
                await async_release_lock(r, lock_key)

        deadline = time.time() + self._wait_timeout_s
        while time.time() < deadline:
            await asyncio.sleep(0.05)
            cached = await self._get_json(full_key, ttl=ttl)
            if cached is not None:
                return cached
        result = await compute_func()
        await self._opt.set(full_key, json.dumps(result), ttl=ttl)
        return result

    async def _get_json(self, full_key: str, *, ttl: int) -> Any | None:
        raw = await self._opt.get(full_key)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        r = await self._opt._ensure_redis()
        if r is not None:
            try:
                await r.expire(full_key, ttl)
            except Exception:
                pass
        return value

    async def invalidate_pattern(self, pattern: str) -> None:
        """SCAN 匹配删除；``*`` / chat 通配 → bump 默认租户 epoch。"""
        if not pattern or pattern in ("*", "chat:*", "chat:v:*"):
            await self.bump_epoch("default")
            return
        r = await self._opt._ensure_redis()
        if r is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    await r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("invalidate_pattern 失败: %s", e)

    async def get_cache_stats(self) -> dict[str, Any]:
        r = await self._opt._ensure_redis()
        if r is None:
            return {"total_keys": 0, "memory_usage": "0B", "hit_rate": 0.0}
        try:
            info = await r.info()
            hits = info.get("keyspace_hits", 0)
            misses = info.get("keyspace_misses", 0)
            total = hits + misses
            return {
                "total_keys": await r.dbsize(),
                "memory_usage": info.get("used_memory_human", "0B"),
                "hit_rate": (hits / total * 100) if total else 0.0,
                "chat_epoch_default": await self.get_epoch("default"),
            }
        except Exception as e:
            logger.warning("get_cache_stats 失败: %s", e)
            return {"total_keys": 0, "memory_usage": "0B", "hit_rate": 0.0}


performance_optimizer = PerformanceOptimizer()
stream_handler = StreamingResponseHandler()
cache_manager = CacheManager(performance_optimizer)
