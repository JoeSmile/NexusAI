"""Global TikHub QPS limiter via Redis token bucket (Task 52 S2).

拍板 (2026-08-18):
- rate 2 QPS, **burst=4**
- Redis 挂 → 本地 sleep(1/rate) 放行 + **告警日志**
- API probe 同桶, max_wait=10s → 超时抛 TikHubRateLimitError(429)
- Worker acquire 超时 → 回 pending + retry_count≤3（见 pipeline）

Env:
- ``SOCIAL_TIKHUB_QPS`` (default 2.0)
- ``SOCIAL_TIKHUB_BURST`` (default 4)
- ``SOCIAL_PROBE_MAX_WAIT_S`` (default 10)
- ``SOCIAL_WORKER_MAX_WAIT_S`` (default 60)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from backend.core.redis_tools import get_sync_redis
from backend.core.social.exceptions import TikHubRateLimitError

logger = logging.getLogger(__name__)

BUCKET_KEY = "social:tikhub:tb"
PROBE_MAX_WAIT_S = 10.0
WORKER_MAX_WAIT_S = 60.0

_LUA_ACQUIRE = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local need = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now_ms
end
local elapsed = (now_ms - ts) / 1000.0
if elapsed < 0 then
  elapsed = 0
end
tokens = math.min(capacity, tokens + elapsed * rate)
local allowed = 0
if tokens >= need then
  tokens = tokens - need
  allowed = 1
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
redis.call('PEXPIRE', key, 120000)
return {allowed, tokens}
"""


def _qps() -> float:
    try:
        return max(0.1, float(os.environ.get("SOCIAL_TIKHUB_QPS", "2.0")))
    except ValueError:
        return 2.0


def _burst() -> float:
    try:
        return max(1.0, float(os.environ.get("SOCIAL_TIKHUB_BURST", "4")))
    except ValueError:
        return 4.0


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _degraded_pass(*, rate: float, sleep: Any, reason: str) -> bool:
    """Local fallback: sleep then allow. Always log alert-level warning."""
    logger.error(
        "[social_tikhub_bucket_degraded] %s; local sleep=%.2fs then allow",
        reason,
        1.0 / rate,
    )
    sleep(1.0 / rate)
    return True


def acquire_tikhub_token(
    *,
    tokens: float = 1.0,
    redis_client: Any | None = None,
    sleep: Any = time.sleep,
    max_wait_s: float | None = None,
) -> bool:
    """Block until a TikHub token is acquired (or timeout).

    Returns True if acquired, False if timed out.
    """
    rate = _qps()
    capacity = _burst()
    wait_budget = (
        max_wait_s
        if max_wait_s is not None
        else _env_float("SOCIAL_WORKER_MAX_WAIT_S", WORKER_MAX_WAIT_S)
    )
    deadline = time.monotonic() + wait_budget
    client = redis_client
    if client is None:
        client = get_sync_redis(decode_responses=True)

    while time.monotonic() < deadline:
        if client is None:
            return _degraded_pass(
                rate=rate, sleep=sleep, reason="redis_unavailable"
            )
        try:
            now_ms = int(time.time() * 1000)
            res = client.eval(
                _LUA_ACQUIRE,
                1,
                BUCKET_KEY,
                str(rate),
                str(capacity),
                str(now_ms),
                str(tokens),
            )
            allowed = int(res[0]) if res else 0
            if allowed == 1:
                return True
            sleep(min(1.0 / rate, max(0.05, deadline - time.monotonic())))
        except Exception as exc:
            return _degraded_pass(
                rate=rate,
                sleep=sleep,
                reason=f"redis_error:{exc}",
            )
    return False


def acquire_for_probe(
    *,
    redis_client: Any | None = None,
    sleep: Any = time.sleep,
) -> None:
    """API probe path: same bucket, max_wait≈10s; timeout → 429."""
    wait_s = _env_float("SOCIAL_PROBE_MAX_WAIT_S", PROBE_MAX_WAIT_S)
    ok = acquire_tikhub_token(
        redis_client=redis_client,
        sleep=sleep,
        max_wait_s=wait_s,
    )
    if not ok:
        raise TikHubRateLimitError(
            f"TikHub 限流排队超时({wait_s:.0f}s),请稍后重试"
        )
