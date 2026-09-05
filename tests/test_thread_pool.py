"""Task 73 slice 6 — default executor follows THREAD_POOL_MAX_WORKERS."""

from __future__ import annotations

import asyncio
import os

import pytest

from packages.performance_config import PerformanceConfig
from packages.thread_pool import (
    get_thread_pool,
    install_default_executor,
    reset_thread_pool_for_tests,
    thread_pool_max_workers,
)


@pytest.fixture(autouse=True)
def _reset_pool():
    reset_thread_pool_for_tests()
    yield
    reset_thread_pool_for_tests()


def test_thread_pool_default_stays_ten(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("THREAD_POOL_MAX_WORKERS", raising=False)
    monkeypatch.setattr(
        PerformanceConfig,
        "THREAD_POOL_MAX_WORKERS",
        int(os.getenv("THREAD_POOL_MAX_WORKERS", "10")),
    )
    assert thread_pool_max_workers() == 10
    assert PerformanceConfig.THREAD_POOL_MAX_WORKERS == 10


def test_get_thread_pool_honors_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(PerformanceConfig, "THREAD_POOL_MAX_WORKERS", 7)
    pool = get_thread_pool()
    assert pool._max_workers == 7


@pytest.mark.asyncio
async def test_install_default_executor_binds_loop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(PerformanceConfig, "THREAD_POOL_MAX_WORKERS", 6)
    n = install_default_executor()
    assert n == 6
    loop = asyncio.get_running_loop()
    ex = loop._default_executor
    assert ex is not None
    assert ex._max_workers == 6
