"""Task 41 S2c — memory stream worker（独立进程入口）。"""

from __future__ import annotations

import logging
import time

from backend.observability.decorators import langfuse_context, observe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("memory_worker")


@observe(name="memory.consolidation")
def process_one(xid: str, data: dict, *, deliveries: int = 1) -> float:
    """处理单条；返回 score（1.0 成功落库 / 0.0 跳过或失败门控）。"""
    import hashlib

    from backend.core.memory.memory_queue import (
        MAX_DELIVERIES,
        ack,
        drop_poison,
        is_tombstoned,
    )
    from backend.core.memory_service import get_unified_memory_service
    from backend.database.vector_ops import list_user_memories_by_prefix

    tenant_id = str(data.get("tenant_id") or "")
    user_id = str(data.get("user_id") or "")
    key = str(data.get("key") or "")
    value = str(data.get("value") or "")
    trace_id = str(data.get("request_trace_id") or "")
    score = 0.0

    try:
        key_fp = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if key else ""
        langfuse_context.update_current_observation(
            metadata={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "request_trace_id": trace_id,
                "key_fp": key_fp,
                "deliveries": deliveries,
                "score": score,
            }
        )
    except Exception:
        pass

    if deliveries > MAX_DELIVERIES:
        drop_poison(xid, data, deliveries=deliveries)
        return 0.0

    if not tenant_id or not user_id or not key:
        ack(xid)
        return 0.0

    # P0-7 fail-closed：Redis 不可用 → 不落库、不 ack（稍后重试）
    tomb = is_tombstoned(tenant_id, user_id)
    if tomb is None:
        logger.error("redis unavailable; refuse write xid=%s", xid)
        return 0.0
    if tomb:
        logger.info("skip tombstoned user=%s xid=%s", user_id, xid)
        ack(xid)
        return 0.0
    # 持久 PG 标记（Redis TTL 过期后仍有效）
    try:
        markers = list_user_memories_by_prefix(tenant_id, user_id, "__forgotten__")
        if any(m.get("key") == "__forgotten__" for m in markers):
            logger.info("skip PG-forgotten user=%s xid=%s", user_id, xid)
            ack(xid)
            return 0.0
    except Exception:
        logger.exception("forgotten marker check failed; refuse write xid=%s", xid)
        return 0.0

    mem = get_unified_memory_service(tenant_id=tenant_id)
    import asyncio
    from datetime import datetime

    from backend.core.audit import write_audit_sync

    write_result = asyncio.run(
        mem.write(
            "warm",
            user_id=user_id,
            key=key,
            value=value,
            confidence=float(data.get("confidence") or 0.5),
            source=str(data.get("source") or "async"),
            embed=bool(data.get("embed", True)),
            enqueued_at=data.get("enqueued_at"),
        )
    )
    # G4 3A：accepted 先审计再 ack；审计失败不 ack（可重放；dedupe_key 幂等）
    if not (isinstance(write_result, dict) and write_result.get("skipped")):
        msg_id = str(data.get("msg_id") or xid)
        key_fp = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        ok = write_audit_sync(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": "memory.write_async",
                "trace_id": trace_id,
                "input_text": f"key_sha256={key_fp}",
                "output_text": msg_id[:64],
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": None,
                "ip_address": "",
                "user_agent": "",
                "dedupe_key": msg_id[:64],
                "created_at": datetime.utcnow(),
            }
        )
        if not ok:
            logger.error("memory.write_async audit failed; refuse ack xid=%s", xid)
            return 0.0
    ack(xid)
    score = 1.0
    try:
        langfuse_context.update_current_observation(metadata={"score": score})
    except Exception:
        pass
    try:
        from backend.core.metrics_memory import record_worker_heartbeat

        record_worker_heartbeat()
    except Exception:
        pass
    return score


def run_forever() -> None:
    from apps.memory_worker.heartbeat import WorkerHeartbeat
    from backend.core.memory.memory_queue import claim_stale, read_group

    logger.info("memory_worker started")
    hb = WorkerHeartbeat("memory")
    hb.start()
    hb.beat()  # first beat before the (blocking) loop
    # I7：启动时先 XAUTOCLAIM 收 PEL
    try:
        stale = claim_stale(count=20)
        for xid, data, deliveries in stale:
            try:
                process_one(xid, data, deliveries=deliveries)
            except Exception:
                logger.exception("claim process failed xid=%s", xid)
    except Exception:
        logger.debug("startup xautoclaim skipped", exc_info=True)

    while True:
        hb.beat()  # liveness progress (watchdog + Redis heartbeat)
        batch = read_group(count=10, block_ms=2000)
        if not batch:
            # 周期再扫一次 stale PEL
            batch = claim_stale(count=10)
            if not batch:
                time.sleep(0.2)
                continue
        for xid, data, deliveries in batch:
            try:
                process_one(xid, data, deliveries=deliveries)
            except Exception:
                logger.exception("process failed xid=%s", xid)


if __name__ == "__main__":
    run_forever()
