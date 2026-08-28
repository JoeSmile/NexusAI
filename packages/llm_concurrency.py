"""LLM 并发槽（Wave H / Task 73）。

语义区分（写死）:
- 本模块管「同时并发」——系统级同时在飞的 LLM 调用数封顶。
- ``rate_limiter`` 管「单位时间速率」——租户级 QPS/配额。
二者互补，不互相替代。

部署注记:
- 切片 0/1：进程内闸门；async 在事件循环上等待，禁止 ``run_in_executor`` 占默认线程池。
- 两级：先全局 ``LLM_CONCURRENCY_LIMIT``（默认 16），后桶 ``LLM_BUCKET_LIMIT``
  （默认 8，key=``key:{LLMKey.id}``，无 id 时回退规范化 base_url）；释放先桶后全局。
- acquire 超时默认 5s → RATE_001 ``llm_slot_busy`` + ``Retry-After: 2``（与租户 QPS 区分）。
- 多 worker 后升级 Redis 分布式计数（切片 2）；勿假定多进程共享本进程内闸门。

Wave H Important F3（2026-08-14 落档）: ``LLMHarness.stream`` **整段**持有并发槽
（含真流式与降级 generate）。长流式会占满两级槽——这是刻意设计（防上游打爆），
不是遗漏；不改为「仅 generate 占槽」。
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from prometheus_client import Gauge, Histogram

from packages.errors import ErrorCode, NexusAIException

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 16
_DEFAULT_BUCKET_LIMIT = 8
_DEFAULT_EMBED_LIMIT = 48
_DEFAULT_EMBED_BUCKET_LIMIT = 8
_DEFAULT_ACQUIRE_TIMEOUT_S = 5.0
_DEFAULT_EMBED_HTTP_TIMEOUT_S = 15.0
_DEFAULT_INFLIGHT_TTL_S = 1200
_REDIS_POLL_S = 0.05
_LLM_SLOT_BUSY = "llm_slot_busy"
_LLM_SLOT_RETRY_AFTER = "2"
_DEFAULT_EMBED_HTTP_TIMEOUT_S = 15.0
_DEFAULT_INFLIGHT_TTL_S = 1200
_REDIS_POLL_S = 0.05

LUA_LLM_SLOT_ACQUIRE = """
-- llm_slot_acquire
local g = redis.call('INCR', KEYS[1])
local glimit = tonumber(ARGV[1])
local blimit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], ttl)
end
if g > glimit then
  redis.call('DECR', KEYS[1])
  if tonumber(redis.call('GET', KEYS[1]) or '0') < 0 then
    redis.call('SET', KEYS[1], 0)
  end
  return 0
end
local b = redis.call('INCR', KEYS[2])
if redis.call('TTL', KEYS[2]) < 0 then
  redis.call('EXPIRE', KEYS[2], ttl)
end
if b > blimit then
  redis.call('DECR', KEYS[2])
  if tonumber(redis.call('GET', KEYS[2]) or '0') < 0 then
    redis.call('SET', KEYS[2], 0)
  end
  redis.call('DECR', KEYS[1])
  if tonumber(redis.call('GET', KEYS[1]) or '0') < 0 then
    redis.call('SET', KEYS[1], 0)
  end
  return 0
end
return 1
"""

LUA_LLM_SLOT_RELEASE = """
-- llm_slot_release
local function decr_floor(key)
  if redis.call('EXISTS', key) == 0 then
    return 0
  end
  local n = redis.call('DECR', key)
  if n < 0 then
    redis.call('SET', key, 0)
    n = 0
  end
  return n
end
decr_floor(KEYS[2])
decr_floor(KEYS[1])
return 1
"""

LLM_SLOTS_IN_FLIGHT = Gauge(
    "nexusai_llm_slots_in_flight",
    "LLM concurrency slots currently held in this process (global cap)",
)
LLM_SLOT_ACQUIRE_WAIT = Histogram(
    "nexusai_llm_slot_acquire_wait_seconds",
    "Time waiting to acquire an LLM concurrency slot",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0),
)
LLM_SLOT_HOLD = Histogram(
    "nexusai_llm_slot_hold_seconds",
    "Time an LLM concurrency slot was held",
    buckets=(0.05, 0.25, 1.0, 5.0, 15.0, 30.0, 60.0, 180.0, 600.0, 1800.0),
)
EMBED_SLOTS_IN_FLIGHT = Gauge(
    "nexusai_embed_slots_in_flight",
    "Embedding HTTP slots currently held in this process (global cap)",
)

_held: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_slot_held", default=False)
_embed_held: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "embed_slot_held", default=False
)
_lock = threading.Lock()
_pool: _TwoLevelPool | None = None
_pool_key: tuple[int, int] | None = None
_embed_pool: _TwoLevelPool | None = None
_embed_pool_key: tuple[int, int] | None = None
_holds = 0
_embed_holds = 0


class _LocalGate:
    """进程内槽：async 在事件循环上等待，sync 在 Condition 上等待，共享同一计数。"""

    def __init__(self, limit: int, *, track_gauge: bool = False) -> None:
        self.limit = limit
        self._track_gauge = track_gauge
        self._n = 0
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._async_waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = []

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._n

    def _set_gauge(self) -> None:
        if self._track_gauge:
            LLM_SLOTS_IN_FLIGHT.set(self._n)

    def _acquire_locked(self) -> bool:
        if self._n < self.limit:
            self._n += 1
            self._set_gauge()
            return True
        return False

    def try_acquire(self) -> bool:
        with self._lock:
            return self._acquire_locked()

    def _drop_waiter(self, fut: asyncio.Future[None]) -> None:
        self._async_waiters = [w for w in self._async_waiters if w[1] is not fut]

    def release(self) -> None:
        to_wake: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = []
        with self._lock:
            if self._n > 0:
                self._n -= 1
            self._set_gauge()
            self._cv.notify()
            if self._async_waiters:
                to_wake = self._async_waiters[:]
                self._async_waiters.clear()
        for loop, fut in to_wake:
            self._wake_future(loop, fut)

    @staticmethod
    def _wake_future(loop: asyncio.AbstractEventLoop, fut: asyncio.Future[None]) -> None:
        def _set() -> None:
            if not fut.done():
                fut.set_result(None)

        try:
            loop.call_soon_threadsafe(_set)
        except RuntimeError:
            pass

    def acquire_sync(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                if self._acquire_locked():
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                if not self._cv.wait(timeout=remaining):
                    return False

    async def acquire_async(self, timeout: float) -> bool:
        if self.try_acquire():
            return True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            fut: asyncio.Future[None] = loop.create_future()
            with self._lock:
                if self._acquire_locked():
                    return True
                self._async_waiters.append((loop, fut))
            try:
                await asyncio.wait_for(fut, timeout=remaining)
            except TimeoutError:
                with self._lock:
                    self._drop_waiter(fut)
                return self.try_acquire()
            except asyncio.CancelledError:
                with self._lock:
                    self._drop_waiter(fut)
                raise


class _TwoLevelPool:
    """先全局后桶；释放先桶后全局。Redis 可用时走共享计数，否则本机闸门。"""

    def __init__(
        self,
        global_limit: int,
        bucket_limit: int,
        *,
        redis_prefix: str = "llm",
    ) -> None:
        self.global_limit = global_limit
        self.bucket_limit = bucket_limit
        self.redis_prefix = redis_prefix
        self.global_gate = _LocalGate(global_limit, track_gauge=False)
        self._buckets: dict[str, _LocalGate] = {}
        self._lock = threading.Lock()

    def bucket_for(self, key: str) -> _LocalGate:
        with self._lock:
            gate = self._buckets.get(key)
            if gate is None or gate.limit != self.bucket_limit:
                gate = _LocalGate(self.bucket_limit)
                self._buckets[key] = gate
            return gate

    def acquire_sync(
        self,
        timeout: float,
        base_url: str | None,
        key_id: str | None = None,
    ) -> tuple[str, str] | None:
        redis_lease = _redis_acquire_sync(timeout, base_url, self, key_id=key_id)
        if isinstance(redis_lease, tuple):
            return redis_lease
        if redis_lease is False:
            return None
        key = provider_bucket_key(key_id=key_id, base_url=base_url)
        t0 = time.monotonic()
        if not self.global_gate.acquire_sync(timeout):
            return None
        remaining = timeout - (time.monotonic() - t0)
        if remaining <= 0:
            self.global_gate.release()
            return None
        try:
            if not self.bucket_for(key).acquire_sync(remaining):
                self.global_gate.release()
                return None
        except BaseException:
            self.global_gate.release()
            raise
        return (key, "local")

    async def acquire_async(
        self,
        timeout: float,
        base_url: str | None,
        key_id: str | None = None,
    ) -> tuple[str, str] | None:
        redis_lease = await _redis_acquire_async(
            timeout, base_url, self, key_id=key_id
        )
        if isinstance(redis_lease, tuple):
            return redis_lease
        if redis_lease is False:
            return None
        key = provider_bucket_key(key_id=key_id, base_url=base_url)
        t0 = time.monotonic()
        if not await self.global_gate.acquire_async(timeout):
            return None
        remaining = timeout - (time.monotonic() - t0)
        if remaining <= 0:
            self.global_gate.release()
            return None
        try:
            if not await self.bucket_for(key).acquire_async(remaining):
                self.global_gate.release()
                return None
        except BaseException:
            self.global_gate.release()
            raise
        return (key, "local")

    def release(self, lease: tuple[str, str]) -> None:
        key, backend = lease
        if backend == "redis":
            _redis_release(key, self.redis_prefix)
            return
        self.bucket_for(key).release()
        self.global_gate.release()


def provider_bucket_key(
    base_url: str | None = None,
    *,
    key_id: str | None = None,
) -> str:
    """Bucket identity: prefer LLMKey.id (never the secret); else normalized URL."""
    kid = str(key_id or "").strip()
    if kid:
        return f"key:{kid}"
    raw = (base_url or "").strip().rstrip("/")
    return f"url:{raw.lower()}" if raw else "default"


def llm_inflight_redis_keys(
    bucket_key: str, *, prefix: str = "llm"
) -> tuple[str, str]:
    digest = hashlib.sha256(bucket_key.encode("utf-8")).hexdigest()[:16]
    return (f"{prefix}:in-flight:global", f"{prefix}:in-flight:{digest}")


def llm_concurrency_limit() -> int:
    """读取 ``LLM_CONCURRENCY_LIMIT``（env），默认 16。"""
    raw = os.getenv("LLM_CONCURRENCY_LIMIT", str(_DEFAULT_LIMIT)).strip()
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_LIMIT
    return max(1, n)


def llm_bucket_limit() -> int:
    """读取 ``LLM_BUCKET_LIMIT``（env），默认 8。"""
    raw = os.getenv("LLM_BUCKET_LIMIT", str(_DEFAULT_BUCKET_LIMIT)).strip()
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_BUCKET_LIMIT
    return max(1, n)


def embed_concurrency_limit() -> int:
    raw = os.getenv("EMBED_CONCURRENCY_LIMIT", str(_DEFAULT_EMBED_LIMIT)).strip()
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_EMBED_LIMIT
    return max(1, n)


def embed_bucket_limit() -> int:
    raw = os.getenv("EMBED_BUCKET_LIMIT", str(_DEFAULT_EMBED_BUCKET_LIMIT)).strip()
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_EMBED_BUCKET_LIMIT
    return max(1, n)


def embed_http_timeout_s() -> float:
    raw = os.getenv("EMBED_HTTP_TIMEOUT_S", str(_DEFAULT_EMBED_HTTP_TIMEOUT_S))
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_EMBED_HTTP_TIMEOUT_S


def llm_acquire_timeout_s() -> float:
    raw = os.getenv("LLM_CONCURRENCY_ACQUIRE_TIMEOUT_S", str(_DEFAULT_ACQUIRE_TIMEOUT_S))
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_ACQUIRE_TIMEOUT_S


def llm_inflight_ttl_s() -> int:
    raw = os.getenv("LLM_INFLIGHT_TTL_S", str(_DEFAULT_INFLIGHT_TTL_S)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_INFLIGHT_TTL_S


def _get_pool() -> _TwoLevelPool:
    global _pool, _pool_key
    key = (llm_concurrency_limit(), llm_bucket_limit())
    with _lock:
        if _pool is None or _pool_key != key:
            _pool = _TwoLevelPool(key[0], key[1], redis_prefix="llm")
            _pool_key = key
        return _pool


def reset_llm_concurrency_for_tests() -> None:
    """测试专用：丢弃闸门，下次按当前 env 重建。"""
    global _pool, _pool_key, _holds, _embed_pool, _embed_pool_key, _embed_holds
    with _lock:
        _pool = None
        _pool_key = None
        _holds = 0
        _embed_pool = None
        _embed_pool_key = None
        _embed_holds = 0
    LLM_SLOTS_IN_FLIGHT.set(0)
    EMBED_SLOTS_IN_FLIGHT.set(0)


def llm_slots_in_flight() -> int:
    """当前进程内已占全局槽数（Prometheus 同值；测试/健康检查可读）。"""
    return _holds


def _note_hold() -> None:
    global _holds
    with _lock:
        _holds += 1
        LLM_SLOTS_IN_FLIGHT.set(_holds)


def _note_release() -> None:
    global _holds
    with _lock:
        _holds = max(0, _holds - 1)
        LLM_SLOTS_IN_FLIGHT.set(_holds)


def _ratelimit_redis() -> object | None:
    try:
        from packages.redis_tools import get_ratelimit_sync_redis

        return get_ratelimit_sync_redis(decode_responses=True)
    except Exception as exc:
        logger.debug("llm_slot redis client skipped: %s", exc)
        return None


def _redis_eval_acquire(
    client: object,
    pool: _TwoLevelPool,
    *,
    bucket_key: str,
) -> bool:
    gkey, bkey = llm_inflight_redis_keys(bucket_key, prefix=pool.redis_prefix)
    n = client.eval(  # type: ignore[union-attr]
        LUA_LLM_SLOT_ACQUIRE,
        2,
        gkey,
        bkey,
        pool.global_limit,
        pool.bucket_limit,
        llm_inflight_ttl_s(),
    )
    return int(n) == 1


def _redis_release(bucket_key: str, prefix: str = "llm") -> None:
    client = _ratelimit_redis()
    if client is None:
        logger.debug("slot redis release skipped (no client)")
        return
    gkey, bkey = llm_inflight_redis_keys(bucket_key, prefix=prefix)
    try:
        client.eval(LUA_LLM_SLOT_RELEASE, 2, gkey, bkey)  # type: ignore[union-attr]
    except Exception as exc:
        logger.debug("slot redis release failed: %s", exc)


def _redis_acquire_sync(
    timeout: float,
    base_url: str | None,
    pool: _TwoLevelPool,
    *,
    key_id: str | None = None,
) -> tuple[str, str] | None | bool:
    """成功返回 lease；Redis 超限等到超时返回 False；Redis 不可用返回 None（回退本机）。"""
    client = _ratelimit_redis()
    if client is None:
        return None
    key = provider_bucket_key(key_id=key_id, base_url=base_url)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if _redis_eval_acquire(client, pool, bucket_key=key):
                return (key, "redis")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_REDIS_POLL_S, remaining))
    except Exception as exc:
        logger.debug("slot redis fallback to local: %s", exc)
        return None


async def _redis_acquire_async(
    timeout: float,
    base_url: str | None,
    pool: _TwoLevelPool,
    *,
    key_id: str | None = None,
) -> tuple[str, str] | None | bool:
    client = _ratelimit_redis()
    if client is None:
        return None
    key = provider_bucket_key(key_id=key_id, base_url=base_url)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            if _redis_eval_acquire(client, pool, bucket_key=key):
                return (key, "redis")
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(_REDIS_POLL_S, remaining))
    except Exception as exc:
        logger.debug("slot redis fallback to local: %s", exc)
        return None


def _timeout_error() -> NexusAIException:
    return NexusAIException(
        code=ErrorCode.RATE_LIMITED.value,
        message=_LLM_SLOT_BUSY,
        detail=_LLM_SLOT_BUSY,
        headers={"Retry-After": _LLM_SLOT_RETRY_AFTER},
    )


def _clear_flag(
    var: contextvars.ContextVar[bool], token: contextvars.Token[bool]
) -> None:
    try:
        var.reset(token)
    except ValueError:
        try:
            var.set(False)
        except Exception:
            pass


@contextmanager
def llm_slot_sync(
    timeout_s: float | None = None,
    *,
    base_url: str | None = None,
    key_id: str | None = None,
) -> Iterator[None]:
    """同步出口（``complete_via_provider``）占用全局+桶两级槽。超时 → RATE_001 / llm_slot_busy。"""
    if _held.get():
        yield
        return
    pool = _get_pool()
    wait = llm_acquire_timeout_s() if timeout_s is None else timeout_s
    t0 = time.perf_counter()
    key = pool.acquire_sync(wait, base_url, key_id=key_id)
    LLM_SLOT_ACQUIRE_WAIT.observe(time.perf_counter() - t0)
    if key is None:
        logger.debug("llm_slot_sync acquire timeout after %.3fs", wait)
        raise _timeout_error()
    token = _held.set(True)
    held_at = time.perf_counter()
    _note_hold()
    try:
        yield
    finally:
        _clear_flag(_held, token)
        LLM_SLOT_HOLD.observe(time.perf_counter() - held_at)
        _note_release()
        pool.release(key)


@asynccontextmanager
async def llm_slot(
    timeout_s: float | None = None,
    *,
    base_url: str | None = None,
    key_id: str | None = None,
) -> AsyncIterator[None]:
    """异步出口（``LLMHarness.generate`` / ``stream``）占用同一两级池。超时 → RATE_001 / llm_slot_busy。

    可重入：stream 降级到 generate 时不二次占槽。
    等待发生在事件循环上，不占用默认 ``ThreadPoolExecutor``。
    stream 整段占两级槽。
    """
    if _held.get():
        yield
        return
    pool = _get_pool()
    wait = llm_acquire_timeout_s() if timeout_s is None else timeout_s
    t0 = time.perf_counter()
    key = await pool.acquire_async(wait, base_url, key_id=key_id)
    LLM_SLOT_ACQUIRE_WAIT.observe(time.perf_counter() - t0)
    if key is None:
        logger.debug("llm_slot acquire timeout after %.3fs", wait)
        raise _timeout_error()
    token = _held.set(True)
    held_at = time.perf_counter()
    _note_hold()
    try:
        yield
    finally:
        _clear_flag(_held, token)
        LLM_SLOT_HOLD.observe(time.perf_counter() - held_at)
        _note_release()
        pool.release(key)


def _get_embed_pool() -> _TwoLevelPool:
    global _embed_pool, _embed_pool_key
    key = (embed_concurrency_limit(), embed_bucket_limit())
    with _lock:
        if _embed_pool is None or _embed_pool_key != key:
            _embed_pool = _TwoLevelPool(key[0], key[1], redis_prefix="embed")
            _embed_pool_key = key
        return _embed_pool


def embed_slots_in_flight() -> int:
    return _embed_holds


def _note_embed_hold() -> None:
    global _embed_holds
    with _lock:
        _embed_holds += 1
        EMBED_SLOTS_IN_FLIGHT.set(_embed_holds)


def _note_embed_release() -> None:
    global _embed_holds
    with _lock:
        _embed_holds = max(0, _embed_holds - 1)
        EMBED_SLOTS_IN_FLIGHT.set(_embed_holds)


def _embed_timeout_error() -> NexusAIException:
    return NexusAIException(
        code=ErrorCode.RATE_LIMITED.value,
        message="embed_concurrency_limit",
        detail="acquire_timeout",
    )


@contextmanager
def embed_slot_sync(
    timeout_s: float | None = None,
    *,
    base_url: str | None = None,
) -> Iterator[None]:
    """真实 embedding HTTP 占用独立两级槽（与 LLM 槽隔离）。"""
    if _embed_held.get():
        yield
        return
    pool = _get_embed_pool()
    wait = llm_acquire_timeout_s() if timeout_s is None else timeout_s
    t0 = time.perf_counter()
    key = pool.acquire_sync(wait, base_url)
    LLM_SLOT_ACQUIRE_WAIT.observe(time.perf_counter() - t0)
    if key is None:
        logger.debug("embed_slot_sync acquire timeout after %.3fs", wait)
        raise _embed_timeout_error()
    token = _embed_held.set(True)
    held_at = time.perf_counter()
    _note_embed_hold()
    try:
        yield
    finally:
        _clear_flag(_embed_held, token)
        LLM_SLOT_HOLD.observe(time.perf_counter() - held_at)
        _note_embed_release()
        pool.release(key)
