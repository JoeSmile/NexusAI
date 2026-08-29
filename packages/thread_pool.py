"""Process default executor aligned with THREAD_POOL_MAX_WORKERS."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def thread_pool_max_workers() -> int:
    from packages.performance_config import PerformanceConfig

    return max(1, int(PerformanceConfig.THREAD_POOL_MAX_WORKERS))


def get_thread_pool() -> ThreadPoolExecutor:
    global _executor
    n = thread_pool_max_workers()
    if _executor is None or getattr(_executor, "_max_workers", None) != n:
        if _executor is not None:
            _executor.shutdown(wait=False)
        _executor = ThreadPoolExecutor(max_workers=n, thread_name_prefix="nxai")
    return _executor


def install_default_executor() -> int:
    """Bind asyncio.to_thread to THREAD_POOL_MAX_WORKERS (not min(32, cpu+4))."""
    n = thread_pool_max_workers()
    loop = asyncio.get_running_loop()
    loop.set_default_executor(get_thread_pool())
    logger.info("default executor workers=%s", n)
    return n


def reset_thread_pool_for_tests() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None
