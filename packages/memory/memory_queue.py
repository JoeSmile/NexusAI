"""Task 41 S2c — Redis Streams 记忆写队列（有效恰好一次）。"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

STREAM_KEY = os.getenv("MEMORY_STREAM_KEY", "mem:write")
GROUP = os.getenv("MEMORY_STREAM_GROUP", "mem-workers")
CONSUMER = os.getenv("MEMORY_STREAM_CONSUMER", f"w-{uuid.uuid4().hex[:8]}")
BACKLOG = int(os.getenv("MEMORY_QUEUE_BACKLOG", "50") or "50")
MIN_IDLE_MS = int(os.getenv("MEMORY_CLAIM_MIN_IDLE_MS", "60000") or "60000")
MAX_DELIVERIES = int(os.getenv("MEMORY_MAX_DELIVERIES", "3") or "3")


def _client():
    from backend.core.redis_tools import get_sync_redis

    # I-5(评审 08-15)：队列独立 db(1)，与缓存/限流(db 0)隔离
    return get_sync_redis(decode_responses=True, db=1)


def ensure_group(redis: Any | None = None) -> bool:
    r = redis or _client()
    if r is None:
        return False
    try:
        r.xgroup_create(STREAM_KEY, GROUP, id="0", mkstream=True)
        return True
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            return True
        logger.debug("xgroup_create failed: %s", exc)
        return False


def queue_depth(redis: Any | None = None) -> int | None:
    r = redis or _client()
    if r is None:
        return None
    try:
        return int(r.xlen(STREAM_KEY))
    except Exception:
        return None


def enqueue_memory_write(payload: dict[str, Any]) -> str | None:
    """XADD；积压超阈值返回 None（调用方同步兜底）。失败静默 None。"""
    r = _client()
    if r is None:
        return None
    try:
        ensure_group(r)
        depth = queue_depth(r)
        if depth is not None and depth >= BACKLOG:
            logger.warning("memory queue backlog=%s >= %s; sync fallback", depth, BACKLOG)
            return None
        body = dict(payload)
        body.setdefault("enqueued_at", time.time())
        body.setdefault("msg_id", str(uuid.uuid4()))
        fields = {"data": json.dumps(body, ensure_ascii=False)}
        maxlen = int(os.getenv("MEMORY_STREAM_MAXLEN", "10000") or "10000")
        try:
            xid = r.xadd(STREAM_KEY, fields, maxlen=maxlen, approximate=True)
        except TypeError:
            # older redis-py
            xid = r.xadd(STREAM_KEY, fields, maxlen=maxlen)
        return str(xid)
    except Exception:
        logger.warning("memory enqueue failed", exc_info=True)
        return None


def _parse_fields(fields: dict[str, Any]) -> dict[str, Any]:
    raw = fields.get("data") or "{}"
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def delivery_count(xid: str, redis: Any | None = None) -> int:
    """PEL times_delivered；查不到按 1。"""
    r = redis or _client()
    if r is None:
        return 1
    try:
        rows = r.xpending_range(STREAM_KEY, GROUP, min=xid, max=xid, count=1)
        if not rows:
            return 1
        row = rows[0]
        if isinstance(row, dict):
            return int(row.get("times_delivered") or row.get("deliveries") or 1)
        # tuple form: (message_id, consumer, time_since_delivered, times_delivered)
        if isinstance(row, (list, tuple)) and len(row) >= 4:
            return int(row[3] or 1)
        return 1
    except Exception:
        return 1


def claim_stale(
    *,
    count: int = 10,
    min_idle_ms: int | None = None,
) -> list[tuple[str, dict[str, Any], int]]:
    """启动/周期 XAUTOCLAIM：收回 PEL 中超时未 ack 的消息。"""
    r = _client()
    if r is None:
        return []
    idle = MIN_IDLE_MS if min_idle_ms is None else min_idle_ms
    out: list[tuple[str, dict[str, Any], int]] = []
    try:
        ensure_group(r)
        start = "0-0"
        # redis-py: (next_start, [(id, fields), ...], ...)
        claimed = r.xautoclaim(
            STREAM_KEY,
            GROUP,
            CONSUMER,
            min_idle_time=idle,
            start_id=start,
            count=count,
        )
        messages = []
        if isinstance(claimed, (list, tuple)) and len(claimed) >= 2:
            messages = claimed[1] or []
        for xid, fields in messages:
            data = _parse_fields(fields or {})
            out.append((str(xid), data, delivery_count(str(xid), r)))
    except Exception:
        logger.debug("xautoclaim failed", exc_info=True)
    return out


def read_group(
    *, count: int = 10, block_ms: int = 1000
) -> list[tuple[str, dict[str, Any], int]]:
    """XREADGROUP 新消息；每条附带 delivery_count。"""
    r = _client()
    if r is None:
        return []
    out: list[tuple[str, dict[str, Any], int]] = []
    try:
        ensure_group(r)
        rows = r.xreadgroup(
            GROUP, CONSUMER, {STREAM_KEY: ">"}, count=count, block=block_ms
        )
        if not rows:
            return out
        for _stream, messages in rows:
            for xid, fields in messages:
                data = _parse_fields(fields or {})
                out.append((str(xid), data, delivery_count(str(xid), r)))
        return out
    except Exception:
        logger.debug("xreadgroup failed", exc_info=True)
        return []


def ack(xid: str) -> None:
    r = _client()
    if r is None:
        return
    try:
        r.xack(STREAM_KEY, GROUP, xid)
    except Exception:
        logger.debug("xack failed", exc_info=True)


def drop_poison(xid: str, data: dict[str, Any], *, deliveries: int) -> None:
    """超重试上限：XACK + 审计 memory.dropped + 指标。"""
    ack(xid)
    try:
        from backend.core.audit import write_audit_sync
        from backend.core.metrics_memory import record_dropped

        write_audit_sync(
            {
                "tenant_id": str(data.get("tenant_id") or ""),
                "user_id": str(data.get("user_id") or ""),
                "action": "memory.dropped",
                "trace_id": str(data.get("request_trace_id") or ""),
                "input_text": str(data.get("key") or "")[:500],
                "output_text": f"deliveries={deliveries}",
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": "MEMORY_MAX_DELIVERIES",
                "ip_address": "",
                "user_agent": "",
                "created_at": __import__("datetime").datetime.utcnow(),
            }
        )
        record_dropped()
    except Exception:
        logger.debug("drop_poison audit/metrics failed", exc_info=True)


def tombstone_user(tenant_id: str, user_id: str) -> bool:
    """forget 时写入 tombstone。返回是否成功写入（失败 = 调用方须 fail-closed）。"""
    r = _client()
    if r is None:
        return False
    try:
        key = f"mem:tombstone:{tenant_id}:{user_id}"
        r.set(key, "1", ex=int(os.getenv("MEMORY_TOMBSTONE_TTL", "86400") or "86400"))
        return True
    except Exception:
        logger.debug("tombstone set failed", exc_info=True)
        return False


def is_tombstoned(tenant_id: str, user_id: str) -> bool | None:
    """True=已 forget；False=未标记；None=Redis 不可用（worker 须拒绝落库）。"""
    r = _client()
    if r is None:
        return None
    try:
        return bool(r.get(f"mem:tombstone:{tenant_id}:{user_id}"))
    except Exception:
        return None


def purge_user_pending(tenant_id: str, user_id: str, *, limit: int = 2000) -> int:
    """尽力从 stream 剔除该用户未消费消息（P0-7）。返回删除条数。"""
    r = _client()
    if r is None:
        return 0
    deleted = 0
    try:
        ensure_group(r)
        rows = r.xrange(STREAM_KEY, min="-", max="+", count=limit)
        for xid, fields in rows or []:
            data = _parse_fields(fields or {})
            if str(data.get("tenant_id")) == tenant_id and str(data.get("user_id")) == user_id:
                try:
                    r.xdel(STREAM_KEY, xid)
                    deleted += 1
                except Exception:
                    pass
    except Exception:
        logger.debug("purge_user_pending failed", exc_info=True)
    return deleted
