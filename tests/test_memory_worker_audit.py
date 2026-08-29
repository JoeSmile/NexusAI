"""G4 / G9 smoke — worker audit + forget residue contract."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

from apps.memory_worker import worker as mw


def test_process_one_audits_accepted_write():
    audits: list[dict] = []

    with patch(
        "packages.memory.memory_queue.is_tombstoned", return_value=False
    ), patch(
        "packages.memory.memory_queue.ack"
    ) as ack, patch(
        "packages.database.vector_ops.list_user_memories_by_prefix", return_value=[]
    ), patch(
        "packages.memory.memory_service.get_unified_memory_service"
    ) as get_mem, patch(
        "packages.audit.write_audit_sync",
        side_effect=lambda r: audits.append(r) or True,
    ), patch(
        "packages.metrics_memory.record_worker_heartbeat"
    ):
        mem = MagicMock()
        mem.write = AsyncMock(return_value={"id": 1})
        get_mem.return_value = mem
        score = mw.process_one(
            "1-0",
            {
                "tenant_id": "t",
                "user_id": "u",
                "key": "entity:x",
                "value": "{}",
                "msg_id": "m1",
                "request_trace_id": "tr",
                "enqueued_at": 1.0,
            },
            deliveries=1,
        )
    assert score == 1.0
    ack.assert_called_once_with("1-0")
    assert any(a.get("action") == "memory.write_async" for a in audits)
    rec = next(a for a in audits if a.get("action") == "memory.write_async")
    fp = hashlib.sha256(b"entity:x").hexdigest()[:32]
    assert rec["input_text"] == f"key_sha256={fp}"
    assert "entity:x" not in rec["input_text"]
    assert rec["output_text"] == "m1"
    mem.write.assert_awaited()
    assert mem.write.await_args.kwargs.get("enqueued_at") == 1.0


def test_process_one_refuses_ack_when_audit_fails():
    with patch(
        "packages.memory.memory_queue.is_tombstoned", return_value=False
    ), patch(
        "packages.memory.memory_queue.ack"
    ) as ack, patch(
        "packages.database.vector_ops.list_user_memories_by_prefix", return_value=[]
    ), patch(
        "packages.memory.memory_service.get_unified_memory_service"
    ) as get_mem, patch(
        "packages.audit.write_audit_sync", return_value=False
    ), patch(
        "packages.metrics_memory.record_worker_heartbeat"
    ):
        mem = MagicMock()
        mem.write = AsyncMock(return_value={"id": 1})
        get_mem.return_value = mem
        score = mw.process_one(
            "1-0",
            {
                "tenant_id": "t",
                "user_id": "u",
                "key": "entity:x",
                "value": "{}",
                "msg_id": "m1",
            },
            deliveries=1,
        )
    assert score == 0.0
    ack.assert_not_called()
