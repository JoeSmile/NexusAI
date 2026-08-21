"""速率限制 — 桶令牌（进程内）+ Redis 分钟桶（Task 52 P1-5）。"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class TokenBucket:
    """租户级桶令牌速率限制器"""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self._tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self._last_refill: dict[str, float] = defaultdict(time.time)

    def consume(self, tenant_id: str) -> bool:
        """消费一个 token，返回是否允许通过"""
        now = time.time()
        elapsed = now - self._last_refill[tenant_id]
        self._tokens[tenant_id] = min(
            self.burst,
            self._tokens[tenant_id] + elapsed * self.rate,
        )
        self._last_refill[tenant_id] = now
        if self._tokens[tenant_id] >= 1:
            self._tokens[tenant_id] -= 1
            return True
        return False

    def reset(self, tenant_id: str) -> None:
        """重置租户的桶"""
        self._tokens[tenant_id] = float(self.burst)
        self._last_refill[tenant_id] = time.time()


_bucket = TokenBucket()


def check_rate_limit(tenant_id: str) -> bool:
    """检查是否被限流"""
    return _bucket.consume(tenant_id)


def check_endpoint_rate_limit(
    tenant_id: str, endpoint: str, *, limit_per_min: int
) -> int | None:
    """Redis 分钟计数。允许返回 None；超限返回 Retry-After 秒。Redis 挂 → 放行。"""
    if limit_per_min <= 0:
        return None
    try:
        from backend.core.redis_tools import get_sync_redis

        client = get_sync_redis(decode_responses=True)
    except Exception:
        return None
    if client is None:
        return None
    tid = tenant_id or "default"
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    key = f"rl:ep:{endpoint}:{tid}:{minute}"
    try:
        n = int(client.incr(key))
        if n == 1:
            client.expire(key, 70)
        if n > limit_per_min:
            return 60
        return None
    except Exception:
        logger.debug("endpoint rate limit skipped", exc_info=True)
        return None
