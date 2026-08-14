"""全局 LLM 并发信号量（Wave H / backlog D8）。

语义区分（写死）:
- 本模块管「同时并发」——系统级同时在飞的 LLM 调用数封顶。
- ``rate_limiter`` 管「单位时间速率」——租户级 QPS/配额。
二者互补，不互相替代。

部署注记:
- 单进程 ``threading.BoundedSemaphore`` 够用（async / sync 出口共享同一池）。
- 多 worker 后升级 Redis 分布式信号量（依赖 D1 Redis 化）；勿假定多进程共享本进程内信号量。
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from backend.core.errors import ErrorCode, NexusAIException

_DEFAULT_LIMIT = 8
_DEFAULT_ACQUIRE_TIMEOUT_S = 30.0

_sem: threading.BoundedSemaphore | None = None
_sem_limit: int | None = None
_lock = threading.Lock()
_held: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_slot_held", default=False)


def llm_concurrency_limit() -> int:
    """读取 ``LLM_CONCURRENCY_LIMIT``（env），默认 8。"""
    raw = os.getenv("LLM_CONCURRENCY_LIMIT", str(_DEFAULT_LIMIT)).strip()
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_LIMIT
    return max(1, n)


def llm_acquire_timeout_s() -> float:
    raw = os.getenv("LLM_CONCURRENCY_ACQUIRE_TIMEOUT_S", str(_DEFAULT_ACQUIRE_TIMEOUT_S))
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_ACQUIRE_TIMEOUT_S


def _get_sem() -> threading.BoundedSemaphore:
    """按当前 limit 懒建/重建信号量（测试可改 env 后 reset）。"""
    global _sem, _sem_limit
    limit = llm_concurrency_limit()
    with _lock:
        if _sem is None or _sem_limit != limit:
            _sem = threading.BoundedSemaphore(limit)
            _sem_limit = limit
        return _sem


def reset_llm_concurrency_for_tests() -> None:
    """测试专用：丢弃信号量，下次按当前 env 重建。"""
    global _sem, _sem_limit
    with _lock:
        _sem = None
        _sem_limit = None


def _timeout_error() -> NexusAIException:
    return NexusAIException(
        code=ErrorCode.RATE_LIMITED.value,
        message="llm_concurrency_limit",
        detail="acquire_timeout",
    )


@contextmanager
def llm_slot_sync(
    timeout_s: float | None = None,
) -> Iterator[None]:
    """同步出口（``complete_via_provider``）占用一个并发槽。超时 → RATE_001 / 429。"""
    if _held.get():
        yield
        return
    sem = _get_sem()
    wait = llm_acquire_timeout_s() if timeout_s is None else timeout_s
    if not sem.acquire(timeout=wait):
        raise _timeout_error()
    token = _held.set(True)
    try:
        yield
    finally:
        _held.reset(token)
        sem.release()


@asynccontextmanager
async def llm_slot(
    timeout_s: float | None = None,
) -> AsyncIterator[None]:
    """异步出口（``LLMHarness.generate`` / ``stream``）占用同一并发池。超时 → RATE_001 / 429。

    可重入：stream 降级到 generate 时不二次占槽。
    """
    if _held.get():
        yield
        return
    sem = _get_sem()
    wait = llm_acquire_timeout_s() if timeout_s is None else timeout_s
    loop = asyncio.get_running_loop()
    acquired = await loop.run_in_executor(None, lambda: sem.acquire(timeout=wait))
    if not acquired:
        raise _timeout_error()
    token = _held.set(True)
    try:
        yield
    finally:
        _held.reset(token)
        sem.release()
