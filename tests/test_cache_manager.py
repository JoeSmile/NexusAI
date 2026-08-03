"""Task 35.04 — CacheManager 单飞 / epoch / 滑动 TTL。"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.services.performance_optimizer import CacheManager, PerformanceOptimizer


class _FakeAsyncRedis:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str):
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n

    async def incr(self, key: str):
        v = int(self.store.get(key) or 0) + 1
        self.store[key] = str(v)
        return v

    async def expire(self, key: str, ttl: int):
        if key in self.store:
            self.ttls[key] = ttl
            return True
        return False

    async def scan(self, cursor=0, match=None, count=200):  # noqa: ANN001
        keys = [k for k in self.store if match is None or _match(match, k)]
        return 0, keys

    async def info(self):
        return {"keyspace_hits": 1, "keyspace_misses": 1, "used_memory_human": "1K"}

    async def dbsize(self):
        return len(self.store)

    async def ping(self):
        return True


def _match(pattern: str, key: str) -> bool:
    if pattern.endswith("*"):
        return key.startswith(pattern[:-1])
    return key == pattern


@pytest.fixture
def cm() -> CacheManager:
    opt = PerformanceOptimizer()
    fake = _FakeAsyncRedis()
    opt._ensure_redis = AsyncMock(return_value=fake)  # type: ignore[method-assign]
    manager = CacheManager(opt)
    manager._fake = fake  # type: ignore[attr-defined]
    return manager


@pytest.mark.asyncio
async def test_get_or_set_caches_and_slides_ttl(cm: CacheManager) -> None:
    calls = {"n": 0}

    async def compute():
        calls["n"] += 1
        return {"ok": True}

    a = await cm.get_or_set("prompt:default:x", compute, ttl=60, tenant_id="t1")
    b = await cm.get_or_set("prompt:default:x", compute, ttl=60, tenant_id="t1")
    assert a == b == {"ok": True}
    assert calls["n"] == 1
    # 命中后续期
    fake = cm._fake  # type: ignore[attr-defined]
    assert any(k.startswith("chat:v:0:t1:") for k in fake.ttls)


@pytest.mark.asyncio
async def test_epoch_bump_misses_old_value(cm: CacheManager) -> None:
    async def compute():
        return {"v": 1}

    await cm.get_or_set("k1", compute, tenant_id="t1")
    await cm.bump_epoch("t1")

    calls = {"n": 0}

    async def compute2():
        calls["n"] += 1
        return {"v": 2}

    out = await cm.get_or_set("k1", compute2, tenant_id="t1")
    assert out == {"v": 2}
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_single_flight_only_one_compute(cm: CacheManager) -> None:
    """两路并发：仅一方拿到锁并回源一次。"""
    gate = asyncio.Event()
    calls = {"n": 0}

    async def compute():
        calls["n"] += 1
        await gate.wait()
        return {"n": calls["n"]}

    t1 = asyncio.create_task(cm.get_or_set("sf", compute, tenant_id="t1"))
    await asyncio.sleep(0.02)
    t2 = asyncio.create_task(cm.get_or_set("sf", compute, tenant_id="t1"))
    await asyncio.sleep(0.02)
    gate.set()
    a, b = await asyncio.gather(t1, t2)
    assert a == b
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_invalidate_star_bumps_epoch(cm: CacheManager) -> None:
    async def compute():
        return {"a": 1}

    await cm.get_or_set("k", compute, tenant_id="default")
    await cm.invalidate_pattern("*")
    assert await cm.get_epoch("default") >= 1
