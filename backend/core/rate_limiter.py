"""速率限制 — Redis 分钟桶（chat QPS + 端点）。

Chat 主路径曾用进程内 TokenBucket：多 worker/多 pod 各桶独立，租户几乎打不满，
表现就是线上不限流。现与 capability/RAG/端点同一契约：Redis INCR+EXPIRE，
跨实例共享；Redis 挂 → 放行（不 500）。
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# 约等于旧 TokenBucket rate=10/s；分钟窗没有独立 burst=20。0 = 关闭。
_DEFAULT_CHAT_PER_MIN = 600


def _chat_limit_per_min() -> int:
    raw = (os.getenv("CHAT_RATE_LIMIT_PER_MIN") or "").strip()
    if not raw:
        return _DEFAULT_CHAT_PER_MIN
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_CHAT_PER_MIN


def check_rate_limit(tenant_id: str) -> bool:
    """租户 chat QPS。True=放行。键 ``rl:ep:chat:{tid}:{YYYYMMDDHHMM}``。"""
    limit = _chat_limit_per_min()
    if limit <= 0:
        return True
    return check_endpoint_rate_limit(tenant_id, "chat", limit_per_min=limit) is None


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
