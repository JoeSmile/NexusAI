"""Process default executor aligned with THREAD_POOL_MAX_WORKERS."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_embed_executor: ThreadPoolExecutor | None = None

T = TypeVar("T")


def thread_pool_max_workers() -> int:
    from packages.performance_config import PerformanceConfig

    return max(1, int(PerformanceConfig.THREAD_POOL_MAX_WORKERS))


def embed_pool_max_workers() -> int:
    raw = (os.getenv("EMBED_THREAD_POOL_MAX_WORKERS") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(2, min(8, thread_pool_max_workers()))


def get_thread_pool() -> ThreadPoolExecutor:
    global _executor
    n = thread_pool_max_workers()
    if _executor is None or getattr(_executor, "_max_workers", None) != n:
        if _executor is not None:
            _executor.shutdown(wait=False)
        _executor = ThreadPoolExecutor(max_workers=n, thread_name_prefix="nxai")
    return _executor


def get_embed_thread_pool() -> ThreadPoolExecutor:
    """Separate pool so slow embed_text does not starve read/audit threads."""
    global _embed_executor
    n = embed_pool_max_workers()
    if _embed_executor is None or getattr(_embed_executor, "_max_workers", None) != n:
        if _embed_executor is not None:
            _embed_executor.shutdown(wait=False)
        _embed_executor = ThreadPoolExecutor(
            max_workers=n, thread_name_prefix="nxai-embed"
        )
    return _embed_executor


def install_default_executor() -> int:
    """Bind asyncio.to_thread to THREAD_POOL_MAX_WORKERS (not min(32, cpu+4))."""
    n = thread_pool_max_workers()
    loop = asyncio.get_running_loop()
    loop.set_default_executor(get_thread_pool())
    logger.info("default executor workers=%s", n)
    return n


def assemble_timeout_s() -> float:
    raw = (os.getenv("MEMORY_ASSEMBLE_TIMEOUT_S") or "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return 20.0


async def run_in_io_pool(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(
            get_thread_pool(), functools.partial(fn, *args, **kwargs)
        )
    return await loop.run_in_executor(get_thread_pool(), fn, *args)


async def run_in_embed_pool(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(
            get_embed_thread_pool(), functools.partial(fn, *args, **kwargs)
        )
    return await loop.run_in_executor(get_embed_thread_pool(), fn, *args)


def reset_thread_pool_for_tests() -> None:
    global _executor, _embed_executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None
    if _embed_executor is not None:
        _embed_executor.shutdown(wait=False)
        _embed_executor = None
