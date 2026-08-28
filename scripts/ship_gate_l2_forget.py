#!/usr/bin/env python3
"""上线闸 L2 / G9 — forget 后队列残留不落库（真 Redis + PG）。

用法（本机已起 postgres + 业务 redis）::

    REDIS_HOST=localhost REDIS_PASSWORD=nexusai_redis \\
    DATABASE_URL=postgresql://nexusai:nexusai_local@localhost:5432/nexusai \\
    uv run python scripts/ship_gate_l2_forget.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

# 须在 import 队列客户端前设好 env
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "nexusai_redis")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://nexusai:nexusai_local@localhost:5432/nexusai",
)


def main() -> int:
    from packages.memory import memory_queue as mq
    from packages.memory.memory_service import get_unified_memory_service
    from backend.database.vector_ops import list_user_memories_by_prefix
    from apps.memory_worker.worker import process_one

    tenant_id = "shipgate"
    user_id = f"g9_{uuid.uuid4().hex[:10]}"
    key = "entity:shipgate_student_pii"
    marker = f"g9-marker-{uuid.uuid4().hex[:8]}"

    print(f"[G9] tenant={tenant_id} user={user_id}")

    r = mq._client()
    if r is None:
        print("FAIL: Redis unavailable")
        return 2
    try:
        r.ping()
    except Exception as e:
        print(f"FAIL: Redis ping {e}")
        return 2
    print("[G9] Redis OK")

    xid = mq.enqueue_memory_write(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "key": key,
            "value": marker,
            "msg_id": f"msg-{uuid.uuid4().hex[:12]}",
            "source": "shipgate_l2",
            "embed": False,
        }
    )
    if not xid:
        print("FAIL: enqueue returned None")
        return 3
    print(f"[G9] enqueued xid={xid}")

    mem = get_unified_memory_service(tenant_id=tenant_id)
    forget = asyncio.run(mem.forget_user(user_id))
    print(f"[G9] forget_user → {forget}")
    tomb = mq.is_tombstoned(tenant_id, user_id)
    print(f"[G9] redis tombstone={tomb}")
    if tomb is not True:
        print("FAIL: expected redis tombstone True after forget")
        return 4

    # 模拟 worker 消费残留（不依赖 compose 镜像构建）
    data = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "key": key,
        "value": marker,
        "msg_id": f"msg-{uuid.uuid4().hex[:12]}",
        "source": "shipgate_l2",
        "embed": False,
        "enqueued_at": 1.0,
    }
    score = process_one(xid, data, deliveries=1)
    print(f"[G9] process_one score={score}")

    rows = list_user_memories_by_prefix(tenant_id, user_id, "entity:")
    leaked = [x for x in rows if marker in str(x.get("value") or "")]
    print(f"[G9] warm entity rows={len(rows)} leaked_marker={len(leaked)}")

    if leaked:
        print("FAIL: forget 后队列残留仍落库")
        return 5
    if score != 0.0:
        print("WARN: expected skip score 0.0 for tombstoned user")
    print("PASS: G9 forget → residual queue write refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
