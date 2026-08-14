"""Wave H — 全局 LLM 并发信号量。"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.errors import ErrorCode, NexusAIException
from backend.core.llm_concurrency import (
    llm_concurrency_limit,
    llm_slot,
    llm_slot_sync,
    reset_llm_concurrency_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_sem(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "2")
    monkeypatch.setenv("LLM_CONCURRENCY_ACQUIRE_TIMEOUT_S", "0.3")
    reset_llm_concurrency_for_tests()
    yield
    reset_llm_concurrency_for_tests()


def test_limit_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "5")
    reset_llm_concurrency_for_tests()
    assert llm_concurrency_limit() == 5


@pytest.mark.asyncio
async def test_concurrent_cap_waits_then_enters():
    """N > limit → 实际并发 ≤ limit；槽释放后后续可进入。"""
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def _job() -> None:
        nonlocal in_flight, peak
        async with llm_slot(timeout_s=2.0):
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1

    await asyncio.gather(*[_job() for _ in range(6)])
    assert peak <= 2
    assert peak >= 1


@pytest.mark.asyncio
async def test_acquire_timeout_raises_rate_001():
    entered = 0
    lock = asyncio.Lock()
    hold = asyncio.Event()

    async def _hold() -> None:
        nonlocal entered
        async with llm_slot(timeout_s=5.0):
            async with lock:
                entered += 1
                if entered >= 2:
                    hold.set()
            await asyncio.sleep(1.0)

    holders = [asyncio.create_task(_hold()) for _ in range(2)]
    await asyncio.wait_for(hold.wait(), timeout=2.0)

    with pytest.raises(NexusAIException) as ei:
        async with llm_slot(timeout_s=0.15):
            pass
    assert ei.value.code == ErrorCode.RATE_LIMITED.value
    assert ei.value.message == "llm_concurrency_limit"

    for t in holders:
        t.cancel()
    await asyncio.gather(*holders, return_exceptions=True)


def test_sync_slot_shares_pool_and_releases():
    with llm_slot_sync(timeout_s=1.0):
        pass
    with llm_slot_sync(timeout_s=0.5):
        pass


@pytest.mark.asyncio
async def test_reentrant_slot_no_double_acquire():
    """stream→generate 同任务重入不占第二槽。"""
    async with llm_slot(timeout_s=1.0):
        async with llm_slot(timeout_s=0.2):
            pass
