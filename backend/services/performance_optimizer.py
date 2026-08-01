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
    """使用 redis.asyncio 的性能优化器（惰性连接，失败降级）。"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._redis = None
        self._lock = asyncio.Lock()
        self.thread_pool = ThreadPoolExecutor(max_workers=10)
        self.cache_ttl = 3600

    async def _ensure_redis(self):
        if self._redis is not None:
            return self._redis
        async with self._lock:
            if self._redis is not None:
                return self._redis
            try:
                from redis.asyncio import from_url as async_redis_from_url

                self._redis = async_redis_from_url(
                    self._redis_url,
                    decode_responses=True,
                    max_connections=50,
                )
            except Exception as e:
                logger.warning("Redis 初始化失败（缓存降级）: %s", e)
                self._redis = None
        return self._redis

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
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

    def cache_key(self, prefix: str, content: str) -> str:
        content_hash = hashlib.md5(content.encode()).hexdigest()
        return f"{prefix}:{content_hash}"

    async def parallel_processing(
        self,
        user_input: str,
        emotion_analyzer,
        safety_checker,
        memory_retriever,
    ) -> dict[str, Any]:
        start_time = time.time()
        loop = asyncio.get_running_loop()

        async def get_or_compute(cache_key: str, sync_fn: Callable[[], Any]):
            cached = await self.get(cache_key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass
            result = await loop.run_in_executor(self.thread_pool, sync_fn)
            try:
                await self.set(cache_key, json.dumps(result))
            except Exception:
                pass
            return result

        emotion_result, safety_result, memory_result = await asyncio.gather(
            get_or_compute(
                self.cache_key("emotion", user_input),
                lambda: emotion_analyzer.analyze(user_input),
            ),
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
            "emotion": emotion_result,
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
    """异步缓存管理器 — 委托 PerformanceOptimizer。"""

    def __init__(self, optimizer: PerformanceOptimizer):
        self._opt = optimizer
        self.default_ttl = 3600

    async def get_or_set(self, key: str, compute_func, ttl: int | None = None) -> Any:
        ttl = ttl or self.default_ttl
        cached = await self._opt.get(key)
        if cached:
            return json.loads(cached)
        result = await compute_func()
        await self._opt.set(key, json.dumps(result), ttl=ttl)
        return result

    async def invalidate_pattern(self, pattern: str) -> None:
        r = await self._opt._ensure_redis()
        if r is None:
            return
        try:
            keys = await r.keys(pattern)
            if keys:
                await r.delete(*keys)
        except Exception as e:
            logger.warning("invalidate_pattern 失败: %s", e)

    async def get_cache_stats(self) -> dict[str, Any]:
        r = await self._opt._ensure_redis()
        if r is None:
            return {"total_keys": 0, "memory_usage": "0B", "hit_rate": 0.0}
        info = await r.info()
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses
        return {
            "total_keys": await r.dbsize(),
            "memory_usage": info.get("used_memory_human", "0B"),
            "hit_rate": (hits / total * 100) if total > 0 else 0.0,
        }


performance_optimizer = PerformanceOptimizer()
stream_handler = StreamingResponseHandler()
cache_manager = CacheManager(performance_optimizer)
