"""Wave H / Task 73 — LLM 并发槽。"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time

import pytest

from packages.errors import ErrorCode, NexusAIException
from backend.core.llm_concurrency import (
    llm_bucket_limit,
    llm_concurrency_limit,
    llm_slot,
    llm_slot_sync,
    llm_slots_in_flight,
    reset_llm_concurrency_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_sem(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "2")
    monkeypatch.setenv("LLM_CONCURRENCY_ACQUIRE_TIMEOUT_S", "0.3")
    monkeypatch.setattr(
        "backend.core.redis_tools.get_ratelimit_sync_redis",
        lambda **_k: None,
    )
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
    assert ei.value.message == "llm_slot_busy"
    assert ei.value.detail == "llm_slot_busy"
    assert ei.value.headers.get("Retry-After") == "2"

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
        assert llm_slots_in_flight() == 1
    assert llm_slots_in_flight() == 0


@pytest.mark.asyncio
async def test_async_acquire_does_not_block_on_default_executor():
    """占满默认线程池后，async 等槽仍能在事件循环上立刻进入（不排队 run_in_executor）。"""
    loop = asyncio.get_running_loop()
    n = min(32, (os.cpu_count() or 1) + 4)
    ready = threading.Event()
    block = threading.Event()
    started_n = 0
    count_lock = threading.Lock()

    def _occupy() -> None:
        nonlocal started_n
        with count_lock:
            started_n += 1
            if started_n >= n:
                ready.set()
        block.wait()

    futs = [loop.run_in_executor(None, _occupy) for _ in range(n)]
    deadline = time.monotonic() + 2.0
    while not ready.is_set():
        if time.monotonic() > deadline:
            pytest.fail("default executor workers did not start")
        await asyncio.sleep(0.01)
    try:
        start = time.monotonic()
        async with asyncio.timeout(1.0):
            async with llm_slot(timeout_s=2.0):
                elapsed = time.monotonic() - start
        assert elapsed < 0.5
    finally:
        block.set()
        await asyncio.gather(*futs)


@pytest.mark.asyncio
async def test_aclose_releases_slot_for_next_acquire(monkeypatch: pytest.MonkeyPatch):
    """SSE 生成器 aclose 后槽必须可被下一个请求拿到（不泄漏到重启）。"""
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "1")
    reset_llm_concurrency_for_tests()

    async def _held_stream():
        async with llm_slot(timeout_s=2.0):
            yield "x"
            await asyncio.sleep(30)

    close_it = asyncio.Event()
    ready = asyncio.Event()

    async def _owner() -> None:
        agen = _held_stream()
        assert await agen.__anext__() == "x"
        ready.set()
        await close_it.wait()
        await agen.aclose()

    owner = asyncio.create_task(_owner())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    assert llm_slots_in_flight() == 1

    with pytest.raises(NexusAIException) as ei:
        async with llm_slot(timeout_s=0.12):
            pass
    assert ei.value.code == ErrorCode.RATE_LIMITED.value
    assert ei.value.message == "llm_slot_busy"
    assert ei.value.detail == "llm_slot_busy"
    assert ei.value.headers.get("Retry-After") == "2"

    close_it.set()
    await owner
    assert llm_slots_in_flight() == 0
    async with llm_slot(timeout_s=0.3):
        pass


@pytest.mark.asyncio
async def test_cancel_releases_slot(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "1")
    reset_llm_concurrency_for_tests()
    entered = asyncio.Event()

    async def _hold() -> None:
        async with llm_slot(timeout_s=2.0):
            entered.set()
            await asyncio.sleep(30)

    task = asyncio.create_task(_hold())
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert llm_slots_in_flight() == 0
    async with llm_slot(timeout_s=0.3):
        pass


@pytest.mark.asyncio
async def test_in_flight_metric_and_sync_share_pool():
    """async 与 sync 共享同一逻辑上限；in_flight 可测。线程不继承 ContextVar 持槽标记。"""
    assert llm_slots_in_flight() == 0
    async with llm_slot(timeout_s=1.0):
        assert llm_slots_in_flight() == 1
        seen: list[int] = []

        def _sync_second_slot() -> None:
            with llm_slot_sync(timeout_s=0.5):
                seen.append(llm_slots_in_flight())

        t = threading.Thread(target=_sync_second_slot)
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert seen == [2]
    assert llm_slots_in_flight() == 0


def test_default_limits_and_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_CONCURRENCY_LIMIT", raising=False)
    monkeypatch.delenv("LLM_BUCKET_LIMIT", raising=False)
    reset_llm_concurrency_for_tests()
    assert llm_concurrency_limit() == 16
    assert llm_bucket_limit() == 8
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "9")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "3")
    reset_llm_concurrency_for_tests()
    assert llm_concurrency_limit() == 9
    assert llm_bucket_limit() == 3


@pytest.mark.asyncio
async def test_different_base_urls_do_not_block(monkeypatch: pytest.MonkeyPatch):
    """两不同 base_url 未超桶上限时互不阻塞。"""
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "4")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "1")
    reset_llm_concurrency_for_tests()
    ready = asyncio.Event()

    async def _hold_a() -> None:
        async with llm_slot(timeout_s=2.0, base_url="https://provider-a.example/v1"):
            ready.set()
            await asyncio.sleep(0.25)

    holder = asyncio.create_task(_hold_a())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    async with llm_slot(timeout_s=0.4, base_url="https://provider-b.example/v1"):
        pass
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


@pytest.mark.asyncio
async def test_same_base_url_bucket_cap(monkeypatch: pytest.MonkeyPatch):
    """同 base_url 超桶上限 → 等待/超时。"""
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "4")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "1")
    reset_llm_concurrency_for_tests()
    ready = asyncio.Event()

    async def _hold() -> None:
        async with llm_slot(timeout_s=2.0, base_url="https://same.example/v1/"):
            ready.set()
            await asyncio.sleep(1.0)

    holder = asyncio.create_task(_hold())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    with pytest.raises(NexusAIException) as ei:
        async with llm_slot(timeout_s=0.15, base_url="https://same.example/v1"):
            pass
    assert ei.value.code == ErrorCode.RATE_LIMITED.value
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


@pytest.mark.asyncio
async def test_global_cap_across_buckets(monkeypatch: pytest.MonkeyPatch):
    """全局在飞达上限 → 不同桶的下一请求也等待/超时。"""
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "1")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "4")
    reset_llm_concurrency_for_tests()
    ready = asyncio.Event()

    async def _hold() -> None:
        async with llm_slot(timeout_s=2.0, base_url="https://a.example"):
            ready.set()
            await asyncio.sleep(1.0)

    holder = asyncio.create_task(_hold())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    with pytest.raises(NexusAIException) as ei:
        async with llm_slot(timeout_s=0.15, base_url="https://b.example"):
            pass
    assert ei.value.code == ErrorCode.RATE_LIMITED.value
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


class _FakeInflightRedis:
    """最小 INCR/DECR + TTL，供 Lua eval 单测。"""

    def __init__(self) -> None:
        self.n: dict[str, int] = {}
        self.expire_at: dict[str, float] = {}
        self.clock = 0.0

    def _get(self, key: str) -> int:
        exp = self.expire_at.get(key)
        if exp is not None and self.clock >= exp:
            self.n.pop(key, None)
            self.expire_at.pop(key, None)
            return 0
        return int(self.n.get(key, 0))

    def eval(self, script: str, num_keys: int, *args: object) -> int:
        keys = [str(a) for a in args[:num_keys]]
        argv = list(args[num_keys:])
        if "llm_slot_acquire" in script:
            gkey, bkey = keys[0], keys[1]
            glob_lim, buck_lim, ttl = int(argv[0]), int(argv[1]), int(argv[2])
            g = self._get(gkey) + 1
            if g > glob_lim:
                return 0
            self.n[gkey] = g
            self.expire_at[gkey] = self.clock + ttl
            b = self._get(bkey) + 1
            if b > buck_lim:
                self.n[gkey] = g - 1
                if self.n[gkey] <= 0:
                    self.n.pop(gkey, None)
                return 0
            self.n[bkey] = b
            self.expire_at[bkey] = self.clock + ttl
            return 1
        if "llm_slot_release" in script:
            for key in reversed(keys):
                n = self._get(key) - 1
                if n <= 0:
                    self.n.pop(key, None)
                    self.expire_at.pop(key, None)
                else:
                    self.n[key] = n
            return 1
        raise AssertionError(script[:120])


@pytest.fixture
def fake_inflight_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeInflightRedis:
    fake = _FakeInflightRedis()
    monkeypatch.setattr(
        "backend.core.redis_tools.get_ratelimit_sync_redis",
        lambda **_k: fake,
    )
    return fake


@pytest.mark.asyncio
async def test_redis_shared_across_reset_workers(
    fake_inflight_redis: _FakeInflightRedis, monkeypatch: pytest.MonkeyPatch
):
    """模拟双 worker：丢弃本机闸门后仍受同一 Redis 全局上限约束。"""
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "1")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "4")
    monkeypatch.setenv("LLM_INFLIGHT_TTL_S", "60")
    reset_llm_concurrency_for_tests()
    ready = asyncio.Event()

    async def _hold() -> None:
        async with llm_slot(timeout_s=2.0, base_url="https://a.example"):
            ready.set()
            await asyncio.sleep(1.0)

    holder = asyncio.create_task(_hold())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    reset_llm_concurrency_for_tests()
    with pytest.raises(NexusAIException) as ei:
        async with llm_slot(timeout_s=0.15, base_url="https://b.example"):
            pass
    assert ei.value.code == ErrorCode.RATE_LIMITED.value
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


@pytest.mark.asyncio
async def test_redis_down_falls_back_to_local(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "1")
    reset_llm_concurrency_for_tests()
    ready = asyncio.Event()

    async def _hold() -> None:
        async with llm_slot(timeout_s=2.0):
            ready.set()
            await asyncio.sleep(1.0)

    holder = asyncio.create_task(_hold())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    with pytest.raises(NexusAIException):
        async with llm_slot(timeout_s=0.15):
            pass
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


@pytest.mark.asyncio
async def test_redis_error_does_not_500(monkeypatch: pytest.MonkeyPatch):
    class _Boom:
        def eval(self, *args: object, **kwargs: object) -> int:
            raise ConnectionError("redis down")

    monkeypatch.setattr(
        "backend.core.redis_tools.get_ratelimit_sync_redis",
        lambda **_k: _Boom(),
    )
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "2")
    reset_llm_concurrency_for_tests()
    async with llm_slot(timeout_s=0.4):
        pass


@pytest.mark.asyncio
async def test_redis_ttl_heals_ghost_counter(
    fake_inflight_redis: _FakeInflightRedis, monkeypatch: pytest.MonkeyPatch
):
    from backend.core.llm_concurrency import LUA_LLM_SLOT_ACQUIRE, llm_inflight_redis_keys

    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "1")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "4")
    monkeypatch.setenv("LLM_INFLIGHT_TTL_S", "1")
    reset_llm_concurrency_for_tests()
    gkey, bkey = llm_inflight_redis_keys("https://ghost.example")
    assert (
        fake_inflight_redis.eval(LUA_LLM_SLOT_ACQUIRE, 2, gkey, bkey, 1, 4, 1) == 1
    )
    with pytest.raises(NexusAIException):
        async with llm_slot(timeout_s=0.15, base_url="https://other.example"):
            pass
    fake_inflight_redis.clock += 2.0
    async with llm_slot(timeout_s=0.3, base_url="https://other.example"):
        pass


def test_provider_bucket_prefers_key_id():
    from backend.core.llm_concurrency import provider_bucket_key

    assert provider_bucket_key(base_url="https://same.example/v1", key_id="k1") == "key:k1"
    assert provider_bucket_key(base_url="HTTPS://Same.example/v1/") == "url:https://same.example/v1"
    assert provider_bucket_key() == "default"


@pytest.mark.asyncio
async def test_different_key_ids_same_url_independent(monkeypatch: pytest.MonkeyPatch):
    """同 base_url、不同 LLMKey.id → 各占一桶，互不阻塞。"""
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "4")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "1")
    reset_llm_concurrency_for_tests()
    ready = asyncio.Event()
    url = "https://same-provider.example/v1"

    async def _hold() -> None:
        async with llm_slot(timeout_s=2.0, base_url=url, key_id="tenant-a"):
            ready.set()
            await asyncio.sleep(0.25)

    holder = asyncio.create_task(_hold())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    async with llm_slot(timeout_s=0.4, base_url=url, key_id="tenant-b"):
        pass
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


@pytest.mark.asyncio
async def test_same_key_id_bucket_cap_default_eight(monkeypatch: pytest.MonkeyPatch):
    """同 key 超桶上限（默认语义 8，本测压到 1）→ 超时 llm_slot_busy。"""
    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "16")
    monkeypatch.setenv("LLM_BUCKET_LIMIT", "1")
    reset_llm_concurrency_for_tests()
    ready = asyncio.Event()

    async def _hold() -> None:
        async with llm_slot(timeout_s=2.0, key_id="shared-key"):
            ready.set()
            await asyncio.sleep(1.0)

    holder = asyncio.create_task(_hold())
    await asyncio.wait_for(ready.wait(), timeout=1.0)
    with pytest.raises(NexusAIException) as ei:
        async with llm_slot(timeout_s=0.15, key_id="shared-key"):
            pass
    assert ei.value.message == "llm_slot_busy"
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


def test_default_acquire_timeout_is_five_seconds(monkeypatch: pytest.MonkeyPatch):
    from backend.core.llm_concurrency import llm_acquire_timeout_s

    monkeypatch.delenv("LLM_CONCURRENCY_ACQUIRE_TIMEOUT_S", raising=False)
    reset_llm_concurrency_for_tests()
    assert llm_acquire_timeout_s() == 5.0


@pytest.mark.asyncio
async def test_slot_busy_http_retry_after_header():
    from starlette.requests import Request

    from packages.errors import nexusai_exception_handler
    from backend.core.llm_concurrency import _timeout_error

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/chat",
        "raw_path": b"/chat",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    request = Request(scope)
    request.state.trace_id = "t"
    resp = await nexusai_exception_handler(request, _timeout_error())
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "2"
    body = json.loads(resp.body)
    assert body["error"]["message"] == "llm_slot_busy"
    assert body["error"]["detail"] == "llm_slot_busy"
